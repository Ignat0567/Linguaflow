"""The interface in Russian, English and German.

Keyed on the Russian source text rather than on invented identifiers. The
usual argument for keys -- that a changed source string silently loses its
translations -- is real, and is answered here by a test that walks every
string in the catalogue and fails when one has no entry. With keys, a call
site reads `t("settings.voice.match")` and nobody can tell what the screen
says without looking it up; this way the code reads as the product does.

Language names are part of the catalogue too. A user running the interface in
German should see «Russisch», not «русский» -- the product translates
languages, so showing their names in only one language would be a poor joke.
"""

from __future__ import annotations

#: Which languages the interface itself is available in.
UI_LANGUAGES = ("ru", "en", "de")

#: The language the interface is being drawn in.
LANGUAGE = "ru"


def set_language(code: str) -> None:
    global LANGUAGE
    LANGUAGE = code if code in UI_LANGUAGES else "ru"


#: What each interface language calls itself, for the picker.
UI_LANGUAGE_NAMES = {"ru": "Русский", "en": "English", "de": "Deutsch"}

#: The names of the languages being translated, in each interface language.
LANGUAGE_NAMES: dict[str, dict[str, str]] = {
    "ru": {"ru": "Русский", "en": "Russian", "de": "Russisch"},
    "en": {"ru": "Английский", "en": "English", "de": "Englisch"},
    "de": {"ru": "Немецкий", "en": "German", "de": "Deutsch"},
    "zh": {"ru": "Китайский", "en": "Chinese", "de": "Chinesisch"},
    "ja": {"ru": "Японский", "en": "Japanese", "de": "Japanisch"},
    "es": {"ru": "Испанский", "en": "Spanish", "de": "Spanisch"},
    "it": {"ru": "Итальянский", "en": "Italian", "de": "Italienisch"},
    "fr": {"ru": "Французский", "en": "French", "de": "Französisch"},
}


def language_name(code: str) -> str:
    """The display name of a translated language, in the interface's own."""
    entry = LANGUAGE_NAMES.get(code)
    if entry is None:
        return code
    return entry.get(LANGUAGE, entry["ru"])


#: Russian source -> (English, German).
CATALOGUE: dict[str, tuple[str, str]] = {
    # -- navigation ----------------------------------------------------
    "Главная": ("Home", "Start"),
    "Реальное время": ("Live", "Echtzeit"),
    "Браузер": ("Browser", "Browser"),
    "Загрузка": ("Upload", "Datei"),
    "История": ("History", "Verlauf"),
    "Настройки": ("Settings", "Einstellungen"),

    # Names the core uses when it says «translating into …». Capitalised
    # to match `languages.describe` after the first letter is raised.
    "Русский": ("Russian", "Russisch"),
    "Английский": ("English", "Englisch"),
    "Немецкий": ("German", "Deutsch"),
    "Китайский": ("Chinese", "Chinesisch"),
    "Японский": ("Japanese", "Japanisch"),
    "Испанский": ("Spanish", "Spanisch"),
    "Итальянский": ("Italian", "Italienisch"),
    "Французский": ("French", "Französisch"),

    # -- home ----------------------------------------------------------
    "Что переводим сегодня?": (
        "What are we translating today?",
        "Was übersetzen wir heute?",
    ),
    "Живой разговор или готовая запись — текст, субтитры или голос.": (
        "A live conversation or a finished recording — text, subtitles or voice.",
        "Ein Gespräch in Echtzeit oder eine fertige Aufnahme — Text, Untertitel "
        "oder Stimme.",
    ),
    "Перевод в реальном времени": ("Live translation", "Übersetzung in Echtzeit"),
    "Субтитры, синхронная озвучка или разговор двух людей на разных языках.": (
        "Subtitles, spoken translation, or two people talking in two languages.",
        "Untertitel, gesprochene Übersetzung oder ein Gespräch zweier Menschen "
        "in zwei Sprachen.",
    ),
    "Начать  →": ("Start  →", "Starten  →"),
    "Загрузка файла": ("Upload a file", "Datei hochladen"),
    "Видео, аудио или песня — транскрипт, субтитры и переведённая озвучка.": (
        "Video, audio or a song — transcript, subtitles and a dubbed soundtrack.",
        "Video, Audio oder ein Lied — Transkript, Untertitel und eine "
        "übersetzte Tonspur.",
    ),
    "Загрузить  →": ("Upload  →", "Hochladen  →"),
    "Последние переводы": ("Recent translations", "Letzte Übersetzungen"),
    "Все  →": ("All  →", "Alle  →"),
    "Пока пусто — переводы появятся здесь.": (
        "Nothing yet — translations will appear here.",
        "Noch nichts — Übersetzungen erscheinen hier.",
    ),
    "Файл": ("File", "Datei"),

    # -- history -------------------------------------------------------
    "История переводов": ("Translation history", "Übersetzungsverlauf"),
    "Пока нет переводов.": ("No translations yet.", "Noch keine Übersetzungen."),
    "Открыть папку": ("Open the folder", "Ordner öffnen"),
    "Очистить историю": ("Clear the history", "Verlauf leeren"),
    "Очистить? Файлы останутся — нажмите ещё раз": (
        "Clear it? The files stay — press again",
        "Wirklich leeren? Die Dateien bleiben — nochmal drücken",
    ),

    # -- realtime ------------------------------------------------------
    "Субтитры": ("Subtitles", "Untertitel"),
    "Разговор": ("Conversation", "Gespräch"),
    "Нажмите, чтобы начать запись": (
        "Press to start recording", "Zum Aufnehmen drücken",
    ),
    "Субтитры появятся здесь": (
        "Subtitles will appear here", "Untertitel erscheinen hier",
    ),
    "Нажмите на кнопку, чтобы начать": (
        "Press the button to begin", "Zum Beginnen die Taste drücken",
    ),
    "Сохранить транскрипт": ("Save transcript", "Transkript speichern"),
    "Окно субтитров": ("Subtitle window", "Untertitelfenster"),
    # -- browser ---------------------------------------------------------
    "Адрес или поиск на YouTube": (
        "Address or YouTube search", "Adresse oder YouTube-Suche",
    ),
    "Включите перевод и запустите видео": (
        "Turn on translation and play a video",
        "Übersetzung einschalten und ein Video abspielen",
    ),
    "Переводить видео": ("Translate video", "Video übersetzen"),
    "Скачать и перевести": ("Download and translate", "Herunterladen und übersetzen"),
    "Видео с этого сайта скачивается перед переводом — откройте пост и включите перевод": (
        "Videos from this site are downloaded first — open the post and turn on translation",
        "Videos dieser Seite werden erst geladen — Beitrag öffnen und Übersetzung einschalten",
    ),
    "Скачиваю видео…": ("Downloading the video…", "Video wird geladen…"),
    "Готовлю перевод: {stage}": (
        "Preparing the translation: {stage}", "Übersetzung wird vorbereitet: {stage}",
    ),
    "Перевод готов · {language} · {count} фраз": (
        "Translation ready · {language} · {count} lines",
        "Übersetzung fertig · {language} · {count} Zeilen",
    ),
    "Перевод готов · {language} · {count} фраз · мужской и женский голос": (
        "Translation ready · {language} · {count} lines · a male and a female voice",
        "Übersetzung fertig · {language} · {count} Zeilen · männliche und weibliche Stimme",
    ),
    "Видео сменилось — включите перевод снова": (
        "The video changed — turn translation on again",
        "Das Video hat gewechselt — Übersetzung erneut einschalten",
    ),
    "Догонять": ("Catch up", "Aufholen"),
    "Пауза — перевод догоняет видео": (
        "Paused — the translation is catching up",
        "Pause — die Übersetzung holt auf",
    ),
    "← К странице": ("← Back to the page", "← Zurück zur Seite"),
    "Не удалось прочитать звук из {name}": (
        "Could not read the sound of {name}", "Der Ton von {name} ist nicht lesbar",
    ),
    "Ссылка — видео скачается, когда начнётся перевод": (
        "Link — the video is downloaded when translation starts",
        "Link — das Video wird beim Start der Übersetzung geladen",
    ),
    "Жду, когда заиграет видео": (
        "Waiting for a video to play", "Warte, bis ein Video läuft",
    ),
    "Слушаю видео": ("Listening to the video", "Höre das Video"),
    "Слушаю видео · {language}": (
        "Listening to the video · {language}", "Höre das Video · {language}",
    ),
    "Идёт реклама — её не перевожу": (
        "An ad is playing — not translating it",
        "Werbung läuft — wird nicht übersetzt",
    ),
    "Сейчас идёт живой перевод на экране «Реальное время».": (
        "A live translation is running on the Live screen.",
        "Auf dem Bildschirm „Echtzeit“ läuft gerade eine Übersetzung.",
    ),
    "Сейчас переводится видео на экране «Браузер».": (
        "A video is being translated on the Browser screen.",
        "Auf dem Bildschirm „Browser“ wird gerade ein Video übersetzt.",
    ),
    # -- realtime (continued) --------------------------------------------
    "Загружаю модели…": ("Loading models…", "Modelle werden geladen…"),
    "Останавливаю…": ("Stopping…", "Wird beendet…"),
    "Слушаю…": ("Listening…", "Ich höre zu…"),
    "Остановлено": ("Stopped", "Beendet"),
    "Живой перевод": ("Live translation", "Echtzeit-Übersetzung"),
    "Сохранено · {duration}": ("Saved · {duration}", "Gespeichert · {duration}"),
    "Автоопределение": ("Detect automatically", "Automatisch erkennen"),

    # -- upload --------------------------------------------------------
    "Медиа": ("Media", "Medien"),
    "Все файлы": ("All files", "Alle Dateien"),
    "Файл не найден: {name}": (
        "File not found: {name}", "Datei nicht gefunden: {name}",
    ),
    "файл": ("file", "Datei"),
    "Исходный язык": ("Source language", "Ausgangssprache"),
    "Перевод на": ("Translate into", "Übersetzen nach"),
    "Выбрать файл": ("Choose a file", "Datei wählen"),
    "Открыть пример": ("Open the example", "Beispiel öffnen"),
    "Перетащите файл": ("Drop a file here", "Datei hierher ziehen"),
    "видео, аудио или песня — MP3, WAV, MP4, MOV": (
        "video, audio or a song — MP3, WAV, MP4, MOV",
        "Video, Audio oder ein Lied — MP3, WAV, MP4, MOV",
    ),
    "Выберите медиафайл": ("Choose a media file", "Mediendatei wählen"),
    "Другой файл": ("Another file", "Andere Datei"),
    "Проверьте язык": ("Check the language", "Sprache prüfen"),
    "Запись звучит как {heard}, а распознавали как {used}. "
    "По неверному языку текст выходит связным и выдуманным — "
    "проверьте выбор языка и звуковую дорожку файла.": (
        "The recording sounds like {heard}, but it was transcribed as "
        "{used}. Under the wrong language the text comes out fluent and "
        "invented — check the language and the file's audio track.",
        "Die Aufnahme klingt nach {heard}, transkribiert wurde sie als "
        "{used}. Mit der falschen Sprache entsteht flüssiger, erfundener "
        "Text — prüfen Sie Sprache und Tonspur der Datei.",
    ),
    "ОК": ("OK", "OK"),
    "Начать перевод": ("Start translating", "Übersetzung starten"),
    "уже {clock}": ("{clock} elapsed", "seit {clock}"),
    "Распознавание готово — дальше перевод, озвучка и сборка видео": (
        "Recognition is done — translation, voice and assembling the video still to come",
        "Erkennung fertig — Übersetzung, Stimme und Videoschnitt folgen noch",
    ),
    "… и ещё {count} субтитров в сохранённых файлах": (
        "… and {count} more subtitles in the saved files",
        "… und {count} weitere Untertitel in den gespeicherten Dateien",
    ),
    "Субтитры (.srt)": ("Subtitles (.srt)", "Untertitel (.srt)"),
    "Перевод (.srt)": ("Translation (.srt)", "Übersetzung (.srt)"),
    "Оба языка (.srt)": ("Both languages (.srt)", "Beide Sprachen (.srt)"),
    "Субтитры (.vtt)": ("Subtitles (.vtt)", "Untertitel (.vtt)"),
    "Текст (.txt)": ("Text (.txt)", "Text (.txt)"),
    "Озвучка (.wav)": ("Dubbed audio (.wav)", "Tonspur (.wav)"),
    "Видео с переводом": ("Translated video", "Video mit Übersetzung"),
    "авто": ("auto", "auto"),

    # -- settings ------------------------------------------------------
    "Языки по умолчанию": ("Default languages", "Standardsprachen"),
    "Голосовой перевод": ("Spoken translation", "Gesprochene Übersetzung"),
    "Озвучивать перевод голосом": (
        "Read the translation aloud", "Übersetzung vorlesen",
    ),
    "Мужской голос мужчинам, женский женщинам": (
        "A male voice for men, a female voice for women",
        "Männliche Stimme für Männer, weibliche für Frauen",
    ),
    "Для видео сохранять копию с новой дорожкой": (
        "For video, save a copy with the new soundtrack",
        "Bei Video eine Kopie mit der neuen Tonspur speichern",
    ),
    "Сокращать перевод, чтобы успевал в реплику": (
        "Shorten the translation so it fits the line",
        "Übersetzung kürzen, damit sie in die Zeile passt",
    ),
    "Чем сокращать": ("What does the shortening", "Womit gekürzt wird"),
    "Только правила": ("Rules only", "Nur Regeln"),
    "Ключ доступа": ("API key", "API-Schlüssel"),
    "Ключ сохранён: {key}": ("Key saved: {key}", "Schlüssel gespeichert: {key}"),
    "Проверить": ("Test", "Testen"),
    "Введите ключ в поле выше.": (
        "Enter a key in the field above.",
        "Geben Sie oben einen Schlüssel ein.",
    ),
    "Проверяю…": ("Testing…", "Wird getestet…"),
    "Ключ работает, модель отвечает.": (
        "The key works, the model answers.",
        "Der Schlüssel funktioniert, das Modell antwortet.",
    ),
    "Сервис ответил, но ничего не прислал.": (
        "The service answered but sent nothing back.",
        "Der Dienst hat geantwortet, aber nichts zurückgeschickt.",
    ),
    "Ключ хранится только на этом компьютере и зашифрован вашей учётной "
    "записью Windows.": (
        "The key is kept on this computer only, encrypted with your Windows "
        "account.",
        "Der Schlüssel bleibt nur auf diesem Rechner und ist mit Ihrem "
        "Windows-Konto verschlüsselt.",
    ),
    "Ключ хранится только на этом компьютере, открытым текстом — система не "
    "предлагает шифрования.": (
        "The key is kept on this computer only, in plain text — this system "
        "offers no encryption for it.",
        "Der Schlüssel bleibt nur auf diesem Rechner, im Klartext — dieses "
        "System bietet dafür keine Verschlüsselung.",
    ),
    "Получить: {where}": ("Get one: {where}", "Erhalten: {where}"),
    "Формат субтитров": ("Subtitle format", "Untertitelformat"),
    "SRT — субтитры с таймингом. Понимают плееры, YouTube и монтажные "
    "программы. Обычный выбор.": (
        "SRT — subtitles with timings. Players, YouTube and editing software "
        "all read it. The usual choice.",
        "SRT — Untertitel mit Zeiten. Player, YouTube und Schnittprogramme "
        "lesen es. Die übliche Wahl.",
    ),
    "VTT — то же самое для веба: HTML5-видео и браузерные плееры.": (
        "VTT — the same thing for the web: HTML5 video and browser players.",
        "VTT — dasselbe fürs Web: HTML5-Video und Browser-Player.",
    ),
    "TXT — только текст, без времени. Для чтения и копирования, не для показа "
    "поверх видео.": (
        "TXT — text only, no timings. For reading and copying, not for showing "
        "over a video.",
        "TXT — nur Text, ohne Zeiten. Zum Lesen und Kopieren, nicht zum "
        "Einblenden über einem Video.",
    ),
    "Где выполняется перевод": (
        "Where translating happens", "Wo übersetzt wird",
    ),
    "Офлайн": ("Offline", "Offline"),
    "Онлайн": ("Online", "Online"),
    "Офлайн — ничего не покидает компьютер. Онлайн отправляет текст во "
    "внешний сервис, который вы выберете.": (
        "Offline — nothing leaves this computer. Online sends the text to an "
        "outside service of your choosing.",
        "Offline — nichts verlässt diesen Rechner. Online sendet den Text an "
        "einen externen Dienst Ihrer Wahl.",
    ),
    "Свой сервер": ("Own server", "Eigener Server"),
    "Источник звука": ("Audio source", "Audioquelle"),
    "Микрофон": ("Microphone", "Mikrofon"),
    "Звук системы": ("System audio", "Systemton"),
    "«Звук системы» — то, что играет из колонок, через WASAPI loopback.": (
        "“System audio” is what comes out of the speakers, via WASAPI loopback.",
        "„Systemton“ ist das, was aus den Lautsprechern kommt, über WASAPI "
        "Loopback.",
    ),
    "Показывать поверх других окон во время записи": (
        "Show on top of other windows while recording",
        "Während der Aufnahme über anderen Fenstern anzeigen",
    ),
    "Скрывать с демонстрации экрана (Meet, Zoom)": (
        "Hide from screen sharing (Meet, Zoom)",
        "Bei Bildschirmfreigabe verbergen (Meet, Zoom)",
    ),
    "Окно остаётся у вас на мониторе, но не попадает в полный экран, которым "
    "вы делитесь. Переключается и на самом окне субтитров, не уходя из "
    "звонка. На «поделиться окном» это не влияет — субтитры и так в другом "
    "окне.": (
        "The window stays on your monitor but does not appear in the full "
        "screen you are sharing. It can also be switched on the subtitle "
        "window itself, without leaving the call. Sharing a single window is "
        "unaffected — the subtitles are a different window anyway.",
        "Das Fenster bleibt auf Ihrem Monitor, erscheint aber nicht im "
        "geteilten Vollbild. Es lässt sich auch am Untertitelfenster selbst "
        "umschalten, ohne den Anruf zu verlassen. Das Teilen eines einzelnen "
        "Fensters ist nicht betroffen — die Untertitel sind ohnehin ein "
        "anderes Fenster.",
    ),
    "Уведомления": ("Notifications", "Benachrichtigungen"),
    "Поднимать окно, когда файл обработан": (
        "Raise the window when a file is done",
        "Fenster in den Vordergrund holen, wenn eine Datei fertig ist",
    ),
    "Акцент": ("Accent", "Akzentfarbe"),
    "Для этого языка голос ещё не задан.": (
        "No voice has been set for this language yet.",
        "Für diese Sprache ist noch keine Stimme festgelegt.",
    ),
    "Язык перевода — {language}. Мужские реплики читает мужской "
    "голос, женские — женский. Кто говорит, определяется по "
    "высоте голоса в оригинале, отдельно для каждой реплики.": (
        "Translating into {language}. Male lines are read in a male voice, "
        "female lines in a female one. Who is speaking is decided from the "
        "pitch of the original, line by line.",
        "Übersetzung nach {language}. Männliche Zeilen liest eine männliche "
        "Stimme, weibliche eine weibliche. Wer spricht, wird aus der "
        "Stimmhöhe des Originals bestimmt, Zeile für Zeile.",
    ),
    "Язык перевода — {language}. Всё читает один голос.": (
        "Translating into {language}. One voice reads everything.",
        "Übersetzung nach {language}. Eine Stimme liest alles.",
    ),

    # -- the three settings added on Day 7 -----------------------------
    "Вид": ("Appearance", "Darstellung"),
    "Светлая тема": ("Light theme", "Helles Design"),
    "Язык интерфейса": ("Interface language", "Sprache der Oberfläche"),
    "Куда сохранять файлы": ("Where to save files", "Speicherort für Dateien"),
    "Выбрать папку": ("Choose a folder", "Ordner wählen"),
    "Настройки, история и ключ: {path}": (
        "Settings, history and key: {path}",
        "Einstellungen, Verlauf und Schlüssel: {path}",
    ),
    "(система перенаправила эту папку)": (
        "(the system redirected this folder)",
        "(das System hat diesen Ordner umgeleitet)",
    ),
    "По умолчанию": ("Default", "Standard"),
    "Выберите папку для готовых файлов": (
        "Choose a folder for finished files",
        "Ordner für fertige Dateien wählen",
    ),

    # -- what the core reports while a job runs ------------------------
    "Открываю источник": ("Opening the source", "Quelle wird geöffnet"),
    "Распознаю ({minutes} мин)": (
        "Recognising ({minutes} min)", "Erkennung läuft ({minutes} Min.)",
    ),
    "Собираю субтитры": ("Building subtitles", "Untertitel werden gebaut"),
    "Язык оригинала совпал с языком перевода": (
        "The source language is the target language",
        "Ausgangs- und Zielsprache sind gleich",
    ),
    "Перевожу на {language}": (
        "Translating into {language}", "Übersetzung nach {language}",
    ),
    "Сокращаю перевод под тайминг": (
        "Shortening the translation to fit",
        "Übersetzung wird auf die Zeit gekürzt",
    ),
    "Сокращаю остальное моделью": (
        "The model shortens the rest", "Den Rest kürzt das Modell",
    ),
    "Озвучиваю перевод": (
        "Speaking the translation", "Übersetzung wird gesprochen",
    ),
    "Озвучиваю перевод, голоса по говорящему": (
        "Speaking the translation, a voice per speaker",
        "Übersetzung wird gesprochen, eine Stimme je Sprecher",
    ),
    "Собираю видео с переводом": (
        "Assembling the translated video",
        "Video mit Übersetzung wird erstellt",
    ),
    "Видео собрать не удалось: {reason}": (
        "The video could not be assembled: {reason}",
        "Das Video konnte nicht erstellt werden: {reason}",
    ),

    "Готово, но результат не показать: {reason}": (
        "Finished, but the result cannot be shown: {reason}",
        "Fertig, aber das Ergebnis kann nicht angezeigt werden: {reason}",
    ),

    "Озвучивать": ("Read aloud", "Vorlesen"),
    "Слова из записи": ("Words in the recording", "Wörter in der Aufnahme"),
    "Имена, термины, названия — через запятую. Распознавание подсказки не "
    "выдумывает, но с ними реже ошибается в том, что слышит впервые.": (
        "Names, terms and titles, separated by commas. Recognition does not "
        "invent from a hint, but it misreads unfamiliar words less often "
        "with one.",
        "Namen, Fachbegriffe und Titel, durch Kommas getrennt. Die Erkennung "
        "erfindet nichts aus einem Hinweis, verhört sich damit aber seltener "
        "bei Unbekanntem.",
    ),
    "например: Kubernetes, Anthropic": (
        "for example: Kubernetes, Anthropic",
        "zum Beispiel: Kubernetes, Anthropic",
    ),

    # -- what the core reports when a job cannot go on ------------------
    "Файл не найден: {path}": (
        "File not found: {path}", "Datei nicht gefunden: {path}",
    ),
    "Не удалось прочитать «{name}» — формат не распознан.": (
        "Could not read “{name}” — the format was not recognised.",
        "„{name}“ konnte nicht gelesen werden — Format nicht erkannt.",
    ),
    "Сервис отклонил ключ доступа. Проверьте его в настройках.": (
        "The service rejected the key. Check it in Settings.",
        "Der Dienst hat den Schlüssel abgelehnt. Prüfen Sie ihn in den "
        "Einstellungen.",
    ),
    "Превышен лимит запросов к сервису перевода. Подождите или переключитесь "
    "в офлайн-режим.": (
        "The translation service's rate limit was reached. Wait, or switch to "
        "offline mode.",
        "Das Anfragelimit des Übersetzungsdienstes ist erreicht. Warten Sie "
        "oder wechseln Sie in den Offline-Modus.",
    ),
    "Не удалось связаться с сервисом перевода. Проверьте интернет или "
    "переключитесь в офлайн-режим.": (
        "Could not reach the translation service. Check the connection, or "
        "switch to offline mode.",
        "Der Übersetzungsdienst ist nicht erreichbar. Prüfen Sie die "
        "Verbindung oder wechseln Sie in den Offline-Modus.",
    ),

    # -- overlay -------------------------------------------------------
    "Linguaflow — субтитры": ("Linguaflow — subtitles", "Linguaflow — Untertitel"),
    "Скрыто с демонстрации": ("Hidden from sharing", "Vor Freigabe verborgen"),
    "Видно на демонстрации": ("Visible when sharing", "Bei Freigabe sichtbar"),
    "Не удалось скрыть с захвата": (
        "Could not hide from capture", "Verbergen nicht möglich",
    ),
    "Субтитры появятся после начала записи": (
        "Subtitles will appear once recording starts",
        "Untertitel erscheinen, sobald die Aufnahme beginnt",
    ),
}


def t(text: str, **values: object) -> str:
    """The given Russian string in the interface's language.

    An untranslated string comes back as it went in. That is deliberate: a
    missing entry should show as Russian in a German interface, which is
    visibly wrong and gets fixed, rather than as an empty label or a key.
    """
    if LANGUAGE != "ru":
        entry = CATALOGUE.get(text)
        if entry is not None:
            text = entry[0] if LANGUAGE == "en" else entry[1]
    return text.format(**values) if values else text


#: Short alias, since it appears on nearly every line of the screens.
_ = t


def missing() -> list[str]:
    """Catalogue entries that are not fully translated, for the tests."""
    return [
        source for source, pair in CATALOGUE.items()
        if len(pair) != 2 or not all(part.strip() for part in pair)
    ]
