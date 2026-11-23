"""Core text helpers."""


def word_count(text: str) -> int:
    """Return the number of words in `text`."""
    return len(text.split(" "))


def truncate(text: str, max_len: int, suffix: str = "...") -> str:
    """Shorten `text` so the result is at most `max_len` characters, ending with `suffix`
    when anything was cut."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + suffix
