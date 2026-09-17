"""Online translation providers.

Used only when the user has explicitly chosen online mode. Both providers here
send the text being translated to a third party, which is the whole reason the
mode is a deliberate choice rather than a fallback.

DeepL is the better translator for the European languages in scope. An
OpenAI-compatible endpoint is the alternative, and is the only one of the two
that can be pointed at a self-hosted model, which makes "online" and "leaves
the building" separable for anyone who runs their own.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

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


class DeepLTranslator:
    name = "DeepL (онлайн)"
    is_offline = False

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


class OpenAICompatibleTranslator:
    """Any endpoint speaking the OpenAI chat-completions shape.

    Sentences are numbered in the prompt and required back numbered, because a
    model asked for "one line per input" will eventually merge two of them, and
    a silent off-by-one shifts every subsequent subtitle onto the wrong
    timestamp. Numbering makes that detectable instead of invisible.
    """

    name = "LLM (онлайн)"
    is_offline = False

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        if not self.api_key:
            raise TranslationError(
                "Для онлайн-перевода через LLM нужен ключ API. Укажите его "
                "в настройках или в переменной OPENAI_API_KEY."
            )
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def supports(self, source: str, target: str) -> bool:
        return source in _LANGUAGE_NAMES and target in _LANGUAGE_NAMES and source != target

    def translate(self, texts: list[str], source: str, target: str) -> list[str]:
        if not texts:
            return []

        numbered = "\n".join(f"{n + 1}. {text}" for n, text in enumerate(texts))
        instruction = (
            f"Translate each numbered line from {_LANGUAGE_NAMES[source]} to "
            f"{_LANGUAGE_NAMES[target]}. These are subtitle lines from speech.\n"
            f"Rules: keep every number, unit and proper name exactly as given; "
            f"do not merge or split lines; do not add commentary.\n"
            f"Reply with exactly {len(texts)} lines in the same numbered form."
        )
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
            {"Authorization": f"Bearer {self.api_key}"},
            self.timeout,
        )
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise TranslationError(
                "Непонятный ответ от сервиса перевода.", json.dumps(data)[:400]
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


def build_cloud_provider(
    service: str = "deepl", **options
):
    if service == "deepl":
        return DeepLTranslator(**options)
    if service in ("openai", "llm"):
        return OpenAICompatibleTranslator(**options)
    raise TranslationError(
        f"Неизвестный онлайн-сервис «{service}». Доступны: deepl, openai."
    )
