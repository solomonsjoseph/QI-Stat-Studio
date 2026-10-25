"""The release version is written in three places. They must match."""
import json
import re
from pathlib import Path

from api.version import __version__

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$")


def test_version_is_semver_and_matches_the_frontend_and_docs():
    assert SEMVER.match(__version__)
    assert json.loads((ROOT / "web" / "package.json").read_text())["version"] == __version__
    assert f'release = "{__version__}"' in (ROOT / "docs" / "source" / "conf.py").read_text()


def test_changelog_has_an_entry_for_the_current_version():
    assert f"## [{__version__}]" in (ROOT / "CHANGELOG.md").read_text()
