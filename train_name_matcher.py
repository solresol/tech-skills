#!/usr/bin/env python3
"""Train a name matching model from labelled CSV data."""

import argparse
import csv
from typing import List

from name_matcher import NameMatcher


def load_pairs(csv_file: str) -> List[tuple[str, str, int]]:
    pairs = []
    with open(csv_file, newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 3:
                continue
            name1, name2, label = row[0], row[1], int(row[2])
            pairs.append((name1, name2, label))
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser(description="Train director name matcher")
    parser.add_argument("training_csv", help="CSV with name1,name2,label")
    parser.add_argument("--model-file", default="name_matcher.pkl", help="Where to store the trained model")
    args = parser.parse_args()

    pairs = load_pairs(args.training_csv)
    matcher = NameMatcher()
    matcher.train(pairs)
    matcher.save(args.model_file)


if __name__ == "__main__":
    main()

