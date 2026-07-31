# OpenDirector movement tracker

The tracker stores OpenDirector director and executive newsletters as an
auditable event history in the existing `techskills` PostgreSQL database on
`raksasa`. Its tables live in the separate `opendirector` schema; the existing
SEC and BoardEx tables in `public` are unchanged.

## Data model

- `opendirector.newsletters` preserves source metadata, the original plain-text
  body, its SHA-256 digest, parsing status, and a direct Gmail source link.
- `opendirector.movements` stores one row per person-event. This matters because
  one newsletter card can describe a departure and its replacement.
- `opendirector.ingestion_runs` records every load and its counts.
- `opendirector.movement_timeline` is the main research view.
- `opendirector.upcoming_movements` shows future effective dates.
- `opendirector.review_queue` exposes uncertain records that still need review.
- `opendirector.company_activity` provides company-level appointment and
  departure counts.

The deterministic parser records its method and confidence on every event.
Lower-confidence legacy-template records remain visible rather than being
silently discarded.

## Loading exported Gmail records

The importer accepts one compact Gmail record or JSON Lines:

```sh
uv run opendirector_ingest.py \
  --input messages.jsonl \
  --database-config db.conf \
  --apply-schema \
  --stats
```

For a pipe from an authorised mailbox connector:

```sh
uv run opendirector_ingest.py \
  --input - \
  --database-config db.conf \
  --stats
```

Re-importing a Gmail message is idempotent. The source row is updated and
deterministically extracted events are replaced. Rows explicitly marked
`manual_override = true` are preserved.

After improving the parser, reprocess stored source text without contacting
Gmail:

```sh
uv run opendirector_ingest.py \
  --reparse-existing \
  --database-config db.conf \
  --stats
```

## Automated updates

The `techskills` crontab on `raksasa` runs a paced batch of 25 least-current
Yahoo price series every day at 06:30 Australia/Sydney time. The deployed job
is `/home/techskills/jobs/opendirector_prices/opendirector_prices_cron.sh`;
timestamped logs are retained for 90 days in its `logs` directory.

The Codex heartbeat remains responsible for the connected-mailbox workflow. It
runs on Tuesdays at 10:00, searches the preceding 14 days of OpenDirector Gmail
messages read-only, imports the overlapping results idempotently, and checks
the live counts, failures, duplicates, and review queue on `raksasa`. It also
refreshes daily prices for confirmed organization-to-security mappings.

Market-history setup, collection and source limitations are described in
[`opendirector_market_history.md`](opendirector_market_history.md).

## Useful queries

```sql
SELECT *
FROM opendirector.movement_timeline
ORDER BY COALESCE(effective_date, week_ending) DESC, organization_name;

SELECT *
FROM opendirector.upcoming_movements;

SELECT *
FROM opendirector.company_activity
ORDER BY movement_count DESC, organization_name;

SELECT *
FROM opendirector.review_queue;
```

## Review convention

An event can be marked reviewed without changing the source extraction:

```sql
UPDATE opendirector.movements
SET review_status = 'reviewed',
    needs_review = false,
    review_notes = 'Checked against the source newsletter',
    updated_at = CURRENT_TIMESTAMP
WHERE id = 123;
```

If a reviewer corrects extracted fields, also set `manual_override = true`.
That prevents a later deterministic reparse from replacing the correction.

## PostgreSQL access on raksasa

The macOS PostgreSQL client used for direct inspection is:

```sh
/Applications/Postgres.app/Contents/Versions/15/bin/psql
```

Connection values remain in `db.conf`; do not place its password in commands,
logs, or exported Gmail records.
