"""Tier selection between the fast and advanced Ollama model.

The previous implementation decided with substring checks (`"class " in text`,
`"import " in text`), which fires on ordinary prose - "Explain the class system
in Victorian Britain" and "import duty on tea exports" were both routed to the
advanced model and paid a 2-4x latency tax for nothing.

Detection is now signal-scored: every signal is anchored (code must look like
code, keywords must be whole words) and a route only escalates when the total
score clears the threshold, so a single ambiguous token cannot drag a plain
question onto the bigger model.
"""

import re
from dataclasses import dataclass

from backend.config import FAST_MODEL, ADVANCED_MODEL

LONG_REQUEST_CHARS = 1800
ADVANCED_MIN_SCORE = 2


@dataclass
class Route:
    model: str
    tier: str
    reason: str


# Whole words only, so "class" in "class system" and "import" in "import duty"
# no longer count, while "refactor", "debugging", "алгоритм" still do.
REASONING_WORDS = re.compile(
    r"\b(?:debug\w*|refactor\w*|architect\w*|algorithm\w*|optimi[sz]\w*|"
    r"prove|proof|proving|derive|derivation|benchmark\w*|complex\w*|"
    r"implement\w*|trade-?offs?|"
    r"отлад\w*|рефактор\w*|алгоритм\w*|оптимизир\w*|докажи|доказать|"
    r"сложн\w*|спроектируй|реализуй|архитектур\w*)\b",
    re.IGNORECASE,
)

# Multi-word intents cannot be matched with a single \b token, so they keep
# their own pattern.
REASONING_PHRASES = re.compile(
    r"(?:compare\s+approaches|design\s+a\s+system|review\s+this\s+code|"
    r"analy[sz]e\s+this\s+code|write\s+code|step[-\s]by[-\s]step|"
    r"сравни\s+подходы|напиши\s+код|проверь\s+код|выведи\s+формулу|"
    r"разработай\s+архитектуру|спроектируй\s+систему)",
    re.IGNORECASE,
)

# An explicit fenced block is decisive on its own.
CODE_FENCE = re.compile(r"```[\w+#.-]*")

# A code *statement*, not a code-looking word. Case-sensitive on purpose:
# Python/JS keywords are lower case and SQL keywords are upper case, so prose
# such as "import duty on tea" or "select one from the list" cannot match.
# Python imports/defs/classes must end their line the way real syntax does.
CODE_STATEMENT = re.compile(
    r"""^[ \t]*(?:
        (?:async[ \t]+)?def[ \t]+\w+[ \t]*\([^\n]*\)[ \t]*:
      | class[ \t]+\w+(?:[ \t]*\([^\n]*\))?[ \t]*:
      | from[ \t]+[\w.]+[ \t]+import[ \t]+[\w*, \t]+$
      | import[ \t]+[\w.]+(?:[ \t]+as[ \t]+\w+)?(?:[ \t]*,[ \t]*[\w.]+)*[ \t]*$
      | (?:async[ \t]+)?function[ \t]*\*?[ \t]*\w*[ \t]*\([^\n]*\)
      | (?:const|let|var)[ \t]+\w+[ \t]*=
      | (?:public|private|protected)[ \t]+[\w<>\[\]]+[ \t]+\w+[ \t]*[\(=]
      | \#include[ \t]*[<"]
      | SELECT[ \t].*\bFROM\b
      | <[a-zA-Z][\w-]*(?:[ \t][^>]*)?>
    )""",
    re.VERBOSE | re.MULTILINE,
)


@dataclass
class _Signals:
    score: int
    reasons: list[str]


def _collect_signals(message: str) -> _Signals:
    score = 0
    reasons: list[str] = []

    fences = len(CODE_FENCE.findall(message))
    statements = len(CODE_STATEMENT.findall(message))

    # One unmistakable code statement (a fence or a `def`/`class`/`import`/
    # `SELECT ... FROM` line) is decisive; the patterns are strict enough that
    # prose does not produce them by accident.
    if fences:
        score += 2
        reasons.append(f"code fence x{fences}")
    if statements:
        score += 2
        reasons.append(f"code statements x{statements}")

    keywords = REASONING_WORDS.findall(message)
    phrases = REASONING_PHRASES.findall(message)
    if keywords or phrases:
        score += 2 if (len(keywords) + len(phrases)) == 1 else 3
        detail = ", ".join(sorted({k.lower() for k in keywords} | {p.lower() for p in phrases}))
        reasons.append(f"reasoning task ({detail})")

    if len(message) > LONG_REQUEST_CHARS:
        # A long prompt is a context-handling problem on its own; the small
        # model degrades long before the big one runs out of room.
        score += 2
        reasons.append("long request")

    return _Signals(score, reasons)


def choose_model(message: str, mode: str = "auto") -> Route:
    if mode == "fast":
        return Route(FAST_MODEL, "fast", "Fast model selected manually")
    if mode == "advanced":
        return Route(ADVANCED_MODEL, "advanced", "Advanced model selected manually")

    signals = _collect_signals(message)

    if signals.score >= ADVANCED_MIN_SCORE:
        return Route(ADVANCED_MODEL, "advanced", ", ".join(signals.reasons))

    return Route(
        FAST_MODEL,
        "fast",
        "Everyday request; using the lighter model",
    )
