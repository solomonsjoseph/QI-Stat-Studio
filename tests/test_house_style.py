"""What the app shows and writes follows the house style: no dash punctuation, curly quotes or stock AI vocabulary."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUNCTUATION = re.compile("[—–“”‘’]")
VOCABULARY = re.compile(r"\b(?:crucial|pivotal|tapestry|testament|delve|showcase[sd]?|vibrant|intricate)\b", re.I)
# These files name the banned words on purpose, to tell the model not to use them.
NAMES_BANNED_WORDS = {"ai_prompts.py", "ai_text.py"}


def _sources():
    for path in list((ROOT / "api").rglob("*.py")) + list((ROOT / "web" / "src").rglob("*.js*")):
        if path.name.endswith((".test.jsx", ".test.js")) or "__pycache__" in path.parts:
            continue
        yield path


def test_no_dash_punctuation_or_curly_quotes_in_source_text():
    offenders = [f"{p.relative_to(ROOT)}:{i}" for p in _sources() for i, line in enumerate(p.read_text().splitlines(), 1) if PUNCTUATION.search(line)]
    assert offenders == []


def test_no_stock_ai_vocabulary_in_source_text():
    offenders = [f"{p.relative_to(ROOT)}:{i}" for p in _sources() if p.name not in NAMES_BANNED_WORDS
                 for i, line in enumerate(p.read_text().splitlines(), 1) if VOCABULARY.search(line)]
    assert offenders == []
