
import re
import subprocess
from urllib.parse import quote_plus


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


def open_website(url: str) -> None:
    subprocess.run(
        ["open", url],
        check=True,
        timeout=10,
    )


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

    text = message.strip().lower()
    text = re.sub(r"[.!?]+$", "", text).strip()
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
            except (subprocess.SubprocessError, OSError) as exc:
                return {
                    "reply": (
                        f"Не удалось открыть {target}: {exc}"
                        if russian
                        else f"Could not open {target}: {exc}"
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

    youtube_search = re.match(
        r"^(?:найди|поищи|search(?:\s+for)?)\s+"
        r"(?:на\s+)?(?:youtube|ютубе?|ютуб)\s+(.+)$",
        text,
    )

    if youtube_search:
        query = youtube_search.group(1).strip()
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

    google_search = re.match(
        r"^(?:найди|поищи|search(?:\s+for)?)\s+"
        r"(?:в\s+)?(?:google|гугле|гугл)\s+(.+)$",
        text,
    )

    if google_search:
        query = google_search.group(1).strip()
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
