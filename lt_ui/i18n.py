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
    "Загрузка": ("Upload", "Datei"),
    "История": ("History", "Verlauf"),
    "Настройки": ("Settings", "Einstellungen"),

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
    "Скачать  ↓": ("Open  ↓", "Öffnen  ↓"),

    # -- realtime ------------------------------------------------------
    "Субтитры": ("Subtitles", "Untertitel"),
    "Текст + озвучка": ("Text + voice", "Text + Stimme"),
    "Разговор": ("Conversation", "Gespräch"),
    "Нажмите, чтобы начать запись": (
        "Press to start recording", "Zum Aufnehmen drücken",
    ),
    "Нажмите на кнопку, чтобы начать": (
        "Press the button to begin", "Zum Beginnen die Taste drücken",
    ),
    "Сохранить транскрипт": ("Save transcript", "Transkript speichern"),
    "Окно субтитров": ("Subtitle window", "Untertitelfenster"),
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
    "Язык перевода — {language}. Мужские реплики читает голос {male}, "
    "женские — {female}. Кто говорит, определяется по высоте голоса в "
    "оригинале, отдельно для каждой реплики.": (
        "Translating into {language}. Male lines are read by {male}, female "
        "lines by {female}. Who is speaking is decided from the pitch of the "
        "original, line by line.",
        "Übersetzung nach {language}. Männliche Zeilen liest {male}, "
        "weibliche {female}. Wer spricht, wird aus der Stimmhöhe des Originals "
        "bestimmt, Zeile für Zeile.",
    ),
    "Язык перевода — {language}. Всё читает один голос, {voice}.": (
        "Translating into {language}. One voice reads everything: {voice}.",
        "Übersetzung nach {language}. Eine Stimme liest alles: {voice}.",
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
    "Внутри программы, по одной папке на задание": (
        "Inside the app, one folder per job",
        "In der Anwendung, ein Ordner pro Auftrag",
    ),
    "Выберите папку для готовых файлов": (
        "Choose a folder for finished files",
        "Ordner für fertige Dateien wählen",
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
