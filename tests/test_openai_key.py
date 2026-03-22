import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import openai_key


class temporary_home:
    def __init__(self, home_path):
        self.home_path = home_path
        self.previous_home = None

    def __enter__(self):
        self.previous_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home_path
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.previous_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.previous_home


def test_project_key_is_preferred():
    with tempfile.TemporaryDirectory() as tmpdir:
        home = Path(tmpdir)
        (home / ".openai.boardskills.key").write_text("boardskills-key\n")
        (home / ".openai.key").write_text("legacy-key\n")

        with temporary_home(tmpdir):
            assert openai_key.resolve_openai_key_file(openai_key.DEFAULT_OPENAI_KEY_FILE) == str(
                home / ".openai.boardskills.key"
            )
            assert openai_key.load_openai_api_key() == "boardskills-key"


def test_legacy_key_is_used_when_project_key_is_missing():
    with tempfile.TemporaryDirectory() as tmpdir:
        home = Path(tmpdir)
        (home / ".openai.key").write_text("legacy-key\n")

        with temporary_home(tmpdir):
            assert openai_key.resolve_openai_key_file(openai_key.DEFAULT_OPENAI_KEY_FILE) == str(
                home / ".openai.key"
            )
            assert openai_key.load_openai_api_key() == "legacy-key"


def test_explicit_missing_path_does_not_fallback():
    with tempfile.TemporaryDirectory() as tmpdir:
        home = Path(tmpdir)
        (home / ".openai.key").write_text("legacy-key\n")

        with temporary_home(tmpdir):
            missing_path = "~/does-not-exist.key"
            try:
                openai_key.load_openai_api_key(missing_path)
            except FileNotFoundError:
                pass
            else:
                raise AssertionError("Expected explicit missing path to raise FileNotFoundError")
