
import ipaddress
import re
import subprocess
from urllib.parse import quote_plus, urlsplit, urlunsplit


WEBSITES = {
    "youtube": "https://www.youtube.com",
    "ютуб": "https://www.youtube.com",
    "google": "https://www.google.com",
    "гугл": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "почта": "https://mail.google.com",
    "github": "https://github.com",
    "гитхаб": "https://github.com",
    "chatgpt": "https://chatgpt.com",
    "netflix": "https://www.netflix.com",
    "instagram": "https://www.instagram.com",
    "инстаграм": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "linkedin": "https://www.linkedin.com",
    "spotify web": "https://open.spotify.com",
}

APPLICATIONS = {
    "telegram": "Telegram",
    "телеграм": "Telegram",
    "spotify": "Spotify",
    "спотифай": "Spotify",
    "whatsapp": "WhatsApp",
    "ватсап": "WhatsApp",
    "discord": "Discord",
    "дискорд": "Discord",
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "safari": "Safari",
    "finder": "Finder",
    "файлы": "Finder",
    "calendar": "Calendar",
    "календарь": "Calendar",
    "notes": "Notes",
    "заметки": "Notes",
    "calculator": "Calculator",
    "калькулятор": "Calculator",
    "preview": "Preview",
    "vscode": "Visual Studio Code",
    "visual studio code": "Visual Studio Code",
    "zoom": "zoom.us",
}

RUSSIAN_COMMAND = re.compile(
    r"^(?:открой|открыть|запусти|запустить|найди|поищи)\b"
)

WEBSITE_OPEN_PATTERNS = (
    re.compile(
        r"^(?:please\s+)?(?:(?:can|could|would)\s+you\s+)?"
        r"(?:open|visit|browse|go\s+to|navigate\s+to|take\s+me\s+to)\s+(.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:открой(?:те)?|открыть|посети(?:те)?|перейди(?:те)?(?:\s+на)?|"
        r"зайди(?:те)?(?:\s+на)?)\s+(.+)$",
        re.IGNORECASE,
    ),
)

SEARCH_COMMAND = (
    r"^(?:(?:please|can\s+you|could\s+you)\s+)?"
    r"(?:найди|поищи|search(?:\s+for)?|find|look\s+up)\s+"
)
YOUTUBE_NAMES = r"(?:youtube|ютубе?|ютуб)"
GOOGLE_NAMES = r"(?:google|гугле|гугл)"


def extract_search_query(text: str, engine_names: str) -> str | None:
    start_engine = re.match(
        SEARCH_COMMAND
        + r"(?:(?:on|in|на|в)\s+)?"
        + engine_names
        + r"\s+(?:for\s+)?(.+)$",
        text,
        re.IGNORECASE,
    )
    if start_engine:
        return start_engine.group(1).strip() or None

    end_engine = re.match(
        SEARCH_COMMAND + r"(.+?)\s+(?:on|in|на|в)\s+" + engine_names + r"$",
        text,
        re.IGNORECASE,
    )
    if end_engine:
        return end_engine.group(1).strip() or None
    return None


def open_website(url: str) -> None:
    subprocess.run(
        ["open", url],
        check=True,
        timeout=10,
    )


def extract_website_open_target(message: str) -> str | None:
    text = message.strip().rstrip(".!?").strip()
    for pattern in WEBSITE_OPEN_PATTERNS:
        match = pattern.match(text)
        if match:
            target = match.group(1).strip()
            target = re.sub(
                r"^(?:(?:the|official)\s+)*(?:website|site)\s+(?:(?:for|of)\s+)?",
                "",
                target,
                flags=re.IGNORECASE,
            )
            target = re.sub(r"^сайт\s+", "", target, flags=re.IGNORECASE)
            target = re.sub(r"\s+(?:please|for me)$", "", target, flags=re.IGNORECASE)
            return target.strip() or None
    return None


def validate_website_url(url: str | None) -> str | None:
    if not isinstance(url, str) or not url or len(url) > 2048:
        return None

    try:
        parsed = urlsplit(url.strip())
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None

    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or parsed.username
        or parsed.password
        or "@" in parsed.netloc
    ):
        return None
    if port is not None:
        return None

    try:
        hostname = hostname.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError:
        return None

    if len(hostname) > 253 or "." not in hostname:
        return None
    if hostname.endswith((".localhost", ".local", ".internal", ".test", ".example")):
        return None
    try:
        ipaddress.ip_address(hostname)
        return None
    except ValueError:
        pass

    labels = hostname.split(".")
    if any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in labels
    ):
        return None

    return urlunsplit(("https", hostname, parsed.path or "", parsed.query, ""))


def open_application(name: str) -> None:
    subprocess.run(
        ["open", "-a", name],
        check=True,
        timeout=10,
    )


def execute_command(message: str):
    """
    Execute only predefined, safe macOS actions.
    Returns a response dictionary, or None if this is not a command.
    """

    original_text = message.strip()
    original_text = re.sub(r"[.!?]+$", "", original_text).strip()
    text = original_text.lower()
    russian = bool(RUSSIAN_COMMAND.match(text))

    open_match = re.match(
        r"^(?:открой|открыть|запусти|запустить|open|launch)\s+(.+)$",
        text,
    )

    if open_match:
        target = open_match.group(1).strip()
        target = re.sub(r"^(?:сайт|приложение)\s+", "", target)

        if target in WEBSITES:
            try:
                open_website(WEBSITES[target])
                return {
                    "reply": (
                        f"Открываю {target}."
                        if russian
                        else f"Opening {target}."
                    ),
                    "action": "open_website",
                }
            except (subprocess.SubprocessError, OSError):
                return {
                    "reply": (
                        f"Не удалось открыть {target}."
                        if russian
                        else f"Could not open {target}."
                    ),
                    "action": "error",
                }

        if target in APPLICATIONS:
            app_name = APPLICATIONS[target]
            try:
                open_application(app_name)
                return {
                    "reply": (
                        f"Запускаю {app_name}."
                        if russian
                        else f"Launching {app_name}."
                    ),
                    "action": "open_application",
                }
            except (subprocess.SubprocessError, OSError) as exc:
                return {
                    "reply": (
                        (
                            f"Не удалось запустить {app_name}. "
                            "Проверь, установлено ли приложение."
                        )
                        if russian
                        else (
                            f"Could not launch {app_name}. "
                            "Check whether it is installed."
                        )
                    ),
                    "action": "error",
                }

    youtube_query = extract_search_query(original_text, YOUTUBE_NAMES)
    if youtube_query:
        query = youtube_query
        url = (
            "https://www.youtube.com/results?search_query="
            + quote_plus(query)
        )
        try:
            open_website(url)
            return {
                "reply": (
                    f"Ищу на YouTube: {query}."
                    if russian
                    else f"Searching YouTube for: {query}."
                ),
                "action": "youtube_search",
            }
        except (subprocess.SubprocessError, OSError):
            return {
                "reply": (
                    "Не удалось открыть поиск YouTube."
                    if russian
                    else "Could not open YouTube search."
                ),
                "action": "error",
            }

    google_query = extract_search_query(original_text, GOOGLE_NAMES)
    if google_query:
        query = google_query
        url = "https://www.google.com/search?q=" + quote_plus(query)

        try:
            open_website(url)
            return {
                "reply": (
                    f"Ищу в Google: {query}."
                    if russian
                    else f"Searching Google for: {query}."
                ),
                "action": "google_search",
            }
        except (subprocess.SubprocessError, OSError):
            return {
                "reply": (
                    "Не удалось открыть Google."
                    if russian
                    else "Could not open Google."
                ),
                "action": "error",
            }

    return None
