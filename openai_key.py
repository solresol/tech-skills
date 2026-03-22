#!/usr/bin/env python3

import os

DEFAULT_OPENAI_KEY_FILE = "~/.openai.boardskills.key"
LEGACY_OPENAI_KEY_FILE = "~/.openai.key"


def _expand(path):
    return os.path.expanduser(path)


def resolve_openai_key_file(path):
    expanded_path = _expand(path)
    default_path = _expand(DEFAULT_OPENAI_KEY_FILE)
    if expanded_path == default_path and not os.path.exists(expanded_path):
        legacy_path = _expand(LEGACY_OPENAI_KEY_FILE)
        if os.path.exists(legacy_path):
            return legacy_path
    return expanded_path


def load_openai_api_key(path=DEFAULT_OPENAI_KEY_FILE):
    with open(resolve_openai_key_file(path)) as key_file:
        return key_file.read().strip()
