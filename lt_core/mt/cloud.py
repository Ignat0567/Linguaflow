"""Online translation providers.

Used only when the user has explicitly chosen online mode. Both providers here
send the text being translated to a third party, which is the whole reason the
mode is a deliberate choice rather than a fallback.

DeepL is the better translator for the European languages in scope. The rest
speak the OpenAI chat-completions protocol, which is what makes them
interchangeable: Groq for speed, OpenAI for quality, and a local server for
anyone who wants the protocol without the third party -- "online" and "leaves
the building" are not the same thing, and this is where they separate.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from .types import TranslationError

# DeepL's own codes. It distinguishes target variants (EN-GB vs EN-US) and
# rejects a plain "EN" as a target.
_DEEPL_SOURCE = {
    "en": "EN", "de": "DE", "ru": "RU", "zh": "ZH",
    "ja": "JA", "es": "ES", "it": "IT", "fr": "FR",
}
_DEEPL_TARGET = {**_DEEPL_SOURCE, "en": "EN-GB"}

_LANGUAGE_NAMES = {
    "en": "English", "de": "German", "ru": "Russian", "zh": "Chinese",
    "ja": "Japanese", "es": "Spanish", "it": "Italian", "fr": "French",
}


def _post(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:400]
        if exc.code in (401, 403):
            raise TranslationError(
                "Сервис отклонил ключ доступа. Проверьте его в настройках.", body
            ) from exc
        if exc.code == 429:
            raise TranslationError(
                "Превышен лимит запросов к сервису перевода. "
                "Подождите или переключитесь в офлайн-режим.", body
            ) from exc
        raise TranslationError(
            f"Сервис перевода ответил ошибкой {exc.code}.", body
        ) from exc
    except urllib.error.URLError as exc:
        raise TranslationError(
            "Не удалось связаться с сервисом перевода. "
            "Проверьте интернет или переключитесь в офлайн-режим.", str(exc)
        ) from exc


def _is_local(url: str) -> bool:
    """Does this endpoint live on the machine the user is sitting at?

    The privacy question is where the text goes, not which protocol carries it.
    A model served from localhost keeps it here.
    """
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


class DeepLTranslator:
    name = "DeepL (онлайн)"
    is_offline = False
    unreliable_on_short_input = False

    def __init__(self, api_key: str | None = None, timeout: float = 30.0) -> None:
        self.api_key = api_key or os.environ.get("DEEPL_API_KEY", "")
        if not self.api_key:
            raise TranslationError(
                "Для DeepL нужен ключ API. Укажите его в настройках "
                "или в переменной DEEPL_API_KEY."
            )
        # Free-tier keys end in ":fx" and use a different host.
        self.endpoint = (
            "https://api-free.deepl.com/v2/translate"
            if self.api_key.endswith(":fx")
            else "https://api.deepl.com/v2/translate"
        )
        self.timeout = timeout

    def supports(self, source: str, target: str) -> bool:
        return source in _DEEPL_SOURCE and target in _DEEPL_TARGET and source != target

    def translate(self, texts: list[str], source: str, target: str) -> list[str]:
        if not texts:
            return []
        payload = {
            "text": texts,
            "source_lang": _DEEPL_SOURCE[source],
            "target_lang": _DEEPL_TARGET[target],
            # The text comes from speech: it has no markup to preserve, and
            # asking DeepL to treat it as XML would mangle stray angle brackets.
            "tag_handling": "plain",
        }
        data = _post(
            self.endpoint, payload,
            {"Authorization": f"DeepL-Auth-Key {self.api_key}"}, self.timeout,
        )
        translations = data.get("translations", [])
        if len(translations) != len(texts):
            raise TranslationError(
                f"DeepL вернул {len(translations)} переводов на {len(texts)} запросов."
            )
        return [entry.get("text", "") for entry in translations]


@dataclass(frozen=True)
class LlmService:
    """An endpoint speaking the OpenAI chat-completions shape."""

    key: str
    label: str
    base_url: str
    default_model: str
    env_var: str
    where_to_get_a_key: str


LLM_SERVICES: dict[str, LlmService] = {
    "openai": LlmService(
        key="openai",
        label="OpenAI",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        env_var="OPENAI_API_KEY",
        where_to_get_a_key="platform.openai.com/api-keys",
    ),
    "groq": LlmService(
        key="groq",
        label="Groq",
        base_url="https://api.groq.com/openai/v1",
        default_model="llama-3.3-70b-versatile",
        env_var="GROQ_API_KEY",
        where_to_get_a_key="console.groq.com/keys",
    ),
    "local": LlmService(
        key="local",
        label="свой сервер",
        # Whatever speaks the protocol: llama.cpp, vLLM, LM Studio, Ollama.
        # "Online" and "leaves the building" are separable for anyone who runs
        # their own; this is the entry that separates them.
        base_url="http://localhost:11434/v1",
        default_model="llama3.1",
        env_var="LOCAL_LLM_API_KEY",
        where_to_get_a_key="ключ обычно не нужен",
    ),
}

# How many subtitle lines to send in one request.
#
# Not a token-budget guess: it is the blast radius. A model given forty lines
# occasionally returns thirty-nine, and the whole request is then discarded
# because the alignment cannot be trusted. Smaller requests lose less work when
# that happens, and keep each call comfortably inside the per-minute token
# limits that Groq's free tier enforces strictly.
DEFAULT_LINES_PER_REQUEST = 40


class OpenAICompatibleTranslator:
    """Translation through a chat model, over the OpenAI protocol.

    Sentences are numbered in the prompt and required back numbered, because a
    model asked for "one line per input" will eventually merge two of them, and
    a silent off-by-one shifts every subsequent subtitle onto the wrong
    timestamp. Numbering makes that detectable instead of invisible.
    """

    # Set per instance: a server on localhost speaks this protocol without the
    # text leaving the machine, and reporting that as "sent to an external
    # service" would be a lie in the direction that matters.
    is_offline = False
    unreliable_on_short_input = False

    def __init__(
        self,
        api_key: str | None = None,
        service: str = "openai",
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 60.0,
        lines_per_request: int = DEFAULT_LINES_PER_REQUEST,
    ) -> None:
        spec = LLM_SERVICES.get(service)
        if spec is None:
            raise TranslationError(
                f"Неизвестный сервис «{service}». "
                f"Доступны: {', '.join(LLM_SERVICES)}."
            )
        self.service = spec
        # Named after where the text actually goes, not after the menu it
        # was chosen from.
        self.name = spec.label
        self.api_key = api_key or os.environ.get(spec.env_var, "")
        if not self.api_key and spec.key != "local":
            raise TranslationError(
                f"Для перевода через {spec.label} нужен ключ API. Укажите его "
                f"в настройках, флагом --api-key или в переменной "
                f"{spec.env_var}. Получить: {spec.where_to_get_a_key}"
            )
        self.base_url = (base_url or spec.base_url).rstrip("/")
        self.model = model or spec.default_model
        self.timeout = timeout
        self.lines_per_request = max(1, lines_per_request)
        self.is_offline = _is_local(self.base_url)
        self.name = (
            f"{spec.label} (на этом компьютере)" if self.is_offline
            else f"{spec.label} (онлайн)"
        )

    def supports(self, source: str, target: str) -> bool:
        return source in _LANGUAGE_NAMES and target in _LANGUAGE_NAMES and source != target

    def translate(self, texts: list[str], source: str, target: str) -> list[str]:
        if not texts:
            return []
        results: list[str] = []
        for start in range(0, len(texts), self.lines_per_request):
            chunk = texts[start:start + self.lines_per_request]
            results.extend(self._translate_chunk(chunk, source, target))
        return results

    def _translate_chunk(
        self, texts: list[str], source: str, target: str
    ) -> list[str]:
        numbered = "\n".join(f"{n + 1}. {text}" for n, text in enumerate(texts))
        instruction = (
            f"Translate each numbered line from {_LANGUAGE_NAMES[source]} to "
            f"{_LANGUAGE_NAMES[target]}. These are subtitle lines from speech.\n"
            f"Rules: keep every number, unit and proper name exactly as given; "
            f"do not merge or split lines; do not add commentary.\n"
            f"Reply with exactly {len(texts)} lines in the same numbered form."
        )
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        data = _post(
            f"{self.base_url}/chat/completions",
            {
                "model": self.model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": instruction},
                    {"role": "user", "content": numbered},
                ],
            },
            headers,
            self.timeout,
        )
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise TranslationError(
                f"Непонятный ответ от {self.service.label}.",
                json.dumps(data)[:400],
            ) from exc
        return _parse_numbered(content, len(texts))


def _parse_numbered(content: str, expected: int) -> list[str]:
    """Pull `expected` lines back out of a numbered reply."""
    import re

    results: dict[int, str] = {}
    for line in content.splitlines():
        match = re.match(r"\s*(\d+)[.)]\s*(.*)$", line)
        if match:
            results[int(match.group(1))] = match.group(2).strip()

    missing = [n for n in range(1, expected + 1) if n not in results]
    if missing:
        raise TranslationError(
            f"Сервис вернул не все строки: нет {len(missing)} из {expected}. "
            f"Соответствие субтитрам нарушено, результат отброшен.",
            content[:400],
        )
    return [results[n] for n in range(1, expected + 1)]


#: Every online service the user can pick, in the order they are offered.
ONLINE_SERVICES: tuple[str, ...] = ("deepl", "groq", "openai", "local")


def build_cloud_provider(service: str = "deepl", **options):
    if service == "deepl":
        options.pop("service", None)
        return DeepLTranslator(**options)
    if service in LLM_SERVICES:
        options.pop("service", None)
        return OpenAICompatibleTranslator(service=service, **options)
    if service == "llm":  # historical alias
        options.pop("service", None)
        return OpenAICompatibleTranslator(service="openai", **options)
    raise TranslationError(
        f"Неизвестный онлайн-сервис «{service}». "
        f"Доступны: {', '.join(ONLINE_SERVICES)}."
    )
