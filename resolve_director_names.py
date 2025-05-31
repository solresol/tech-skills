#!/usr/bin/env python3
"""Populate canonical director tables based on extracted names."""

import argparse
from typing import List, Tuple
import os

import pgconnect
from name_matcher import NameMatcher, normalise_name


def fetch_distinct_names(cursor, source_view: str) -> List[str]:
    cursor.execute(f"SELECT DISTINCT director_name FROM {source_view}")
    return [r[0] for r in cursor.fetchall()]


def load_matcher(model_file: str | None) -> NameMatcher | None:
    if model_file and os.path.exists(model_file):
        return NameMatcher.load(model_file)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve director names")
    parser.add_argument("--database-config", default="db.conf", help="DB config file")
    parser.add_argument("--model-file", help="Trained matcher model")
    parser.add_argument("--threshold", type=float, default=0.8, help="Match probability threshold")
    parser.add_argument("--source-view", default="director_mentions", help="Where to read names from")
    args = parser.parse_args()

    conn = pgconnect.connect(args.database_config)
    read = conn.cursor()
    write = conn.cursor()

    matcher = load_matcher(args.model_file)

    existing = {}
    write.execute("SELECT id, canonical_name FROM directors")
    for row in write.fetchall():
        existing[row[1]] = row[0]

    names = fetch_distinct_names(read, args.source_view)

    for name in names:
        canonical = normalise_name(name)
        director_id = existing.get(canonical)

        if director_id is None and matcher is not None:
            # attempt fuzzy match
            best_id = None
            best_score = 0.0
            for canon, did in existing.items():
                score = matcher.score(name, canon)
                if score > best_score:
                    best_score = score
                    best_id = did
            if best_score >= args.threshold:
                director_id = best_id

        if director_id is None:
            write.execute(
                "INSERT INTO directors (canonical_name) VALUES (%s) RETURNING id",
                [canonical],
            )
            director_id = write.fetchone()[0]
            existing[canonical] = director_id

        write.execute(
            "INSERT INTO director_name_aliases (director_id, alias, source) "
            "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            [director_id, name, args.source_view],
        )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()

