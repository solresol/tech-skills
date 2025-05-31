#!/usr/bin/env python3
"""Utilities for matching director names.

Provides normalisation routines and a small logistic-regression
classifier for determining when two names likely refer to the same
individual.
"""

from __future__ import annotations

import re
import unicodedata
import pickle
from typing import Iterable, Tuple

from sklearn.linear_model import LogisticRegression

import director_name_handling

SUFFIXES = {"JR", "SR", "II", "III", "IV", "V"}


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c))


def normalise_name(name: str) -> str:
    """Return a canonical representation of a person's name."""
    name = _strip_accents(name)
    name = director_name_handling.remove_name_suffixes(name)
    name = re.sub(r"[^A-Za-z0-9 ]", "", name)
    parts = name.upper().split()
    parts = [p for p in parts if p not in SUFFIXES]
    return " ".join(parts)


def _ngrams(text: str, n: int = 3) -> set[str]:
    padded = f" {text} "
    return {padded[i : i + n] for i in range(len(padded) - n + 1)}


def trigram_similarity(a: str, b: str) -> float:
    """Jaccard similarity on character trigrams of two strings."""
    ng_a = _ngrams(normalise_name(a))
    ng_b = _ngrams(normalise_name(b))
    if not ng_a or not ng_b:
        return 0.0
    intersection = len(ng_a & ng_b)
    union = len(ng_a | ng_b)
    return intersection / union


def levenshtein(a: str, b: str) -> int:
    """Simple Levenshtein distance implementation."""
    a = normalise_name(a)
    b = normalise_name(b)
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            insert = current[j - 1] + 1
            delete = previous[j] + 1
            replace = previous[j - 1] + (ca != cb)
            current.append(min(insert, delete, replace))
        previous = current
    return previous[-1]


def feature_vector(a: str, b: str) -> list[float]:
    return [
        trigram_similarity(a, b),
        levenshtein(a, b),
    ]


class NameMatcher:
    """Thin wrapper around ``sklearn`` logistic regression for name matching."""

    def __init__(self, model: LogisticRegression | None = None):
        self.model = model or LogisticRegression()

    def train(self, pairs: Iterable[Tuple[str, str, int]]):
        X = []
        y = []
        for n1, n2, label in pairs:
            X.append(feature_vector(n1, n2))
            y.append(label)
        self.model.fit(X, y)

    def score(self, a: str, b: str) -> float:
        X = [feature_vector(a, b)]
        return float(self.model.predict_proba(X)[0][1])

    def save(self, path: str):
        with open(path, "wb") as f:
            pickle.dump(self.model, f)

    @classmethod
    def load(cls, path: str) -> "NameMatcher":
        with open(path, "rb") as f:
            model = pickle.load(f)
        return cls(model)

