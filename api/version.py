"""Single source for the release version (SemVer 2.0.0, so a beta is a pre-release such as 1.0.0-beta.1).
web/package.json and docs/source/conf.py must carry the same string; tests/test_version.py checks it."""

__version__ = "1.0.0-beta.1"
