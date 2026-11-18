from dataclasses import dataclass
from backend.config import FAST_MODEL, ADVANCED_MODEL

@dataclass
class Route:
    model: str
    tier: str
    reason: str

ADVANCED_KEYWORDS = (
    "debug", "refactor", "architecture", "algorithm", "optimize", "prove", "derive",
    "compare approaches", "trade-off", "tradeoff", "design a system", "implement",
    "write code", "review this code", "complex", "step by step", "analyze this code",
    "разработай архитектуру", "отлад", "рефактор", "алгоритм", "оптимизируй",
    "докажи", "выведи формулу", "сравни подходы", "напиши код", "проверь код",
    "сложн", "спроектируй систему", "реализуй",
)


def choose_model(message: str, mode: str = "auto") -> Route:
    normalized = message.lower()
    if mode == "fast":
        return Route(FAST_MODEL, "fast", "Fast model selected manually")
    if mode == "advanced":
        return Route(ADVANCED_MODEL, "advanced", "Advanced model selected manually")
    if mode != "auto":
        mode = "auto"

    long_request = len(message) > 1800
    keyword_match = any(word in normalized for word in ADVANCED_KEYWORDS)
    code_like = ("```" in message or "def " in message or "class " in message or "import " in message)
    if long_request or keyword_match or code_like:
        reasons = []
        if long_request: reasons.append("long request")
        if keyword_match: reasons.append("reasoning/coding task")
        if code_like: reasons.append("code detected")
        return Route(ADVANCED_MODEL, "advanced", ", ".join(reasons))
    return Route(FAST_MODEL, "fast", "Everyday request; using the lighter model")
