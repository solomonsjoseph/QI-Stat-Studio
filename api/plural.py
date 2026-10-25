"""Counts written as plain English: "1 point", "2 points"."""


def plural(n, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"
