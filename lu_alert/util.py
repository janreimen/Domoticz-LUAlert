"""Small helpers shared by the modules."""
import re
from typing import Any, Optional


def safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    """int(float(value)) for numbers and numeric text; ``default`` for everything else (also for bool)."""
    if value is None or value == "" or isinstance(value, bool):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def shorten(text: Any, limit: int) -> str:
    """One line of at most ``limit`` characters: white space collapsed, a cut text ends in '...'."""
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


_TAG = re.compile(r"<[^>]*>")
# the end of a block element or a <br>, with or without a namespace prefix (ElementTree writes <ns0:p> for <p>)
_BREAKS = re.compile(r"(?i)<\s*(?:/\s*(?:[\w.-]+:)?(?:p|li|tr|td|th|div|ul|ol|table|h[1-6])|(?:[\w.-]+:)?br)\b[^>]*>")


def plain_text(markup: Optional[str]) -> str:
    """Text of a CAP description: tags removed, line breaks kept as spaces, entities left as the XML parser made them."""
    if not markup:
        return ""
    text = _BREAKS.sub(" ", markup)
    text = _TAG.sub("", text)
    return " ".join(text.split())


def split_list(text: Any) -> list:
    """'a, b;c' -> ['a', 'b', 'c'] (comma, semicolon and line break separate; empty items are dropped)."""
    if text is None:
        return []
    return [part.strip() for part in re.split(r"[,;\n]", str(text)) if part.strip()]
