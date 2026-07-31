# OpenDirector market and historical leadership data

## Current implementation

Daily ASX price history is stored in the existing `opendirector` PostgreSQL
schema on `raksasa`.

- `market_securities` is the security master. Current companies are refreshed
  from the official ASX company-directory CSV.
- `organization_security_matches` maps the organization names used in
  OpenDirector newsletters to securities. Only confirmed mappings feed the
  movement-link view.
- `daily_prices` stores raw OHLC prices, adjusted close, volume, dividends and
  split ratios with an explicit provider label.
- `price_ingestion_runs` and `price_ingestion_failures` make every load
  auditable.
- `price_coverage` summarizes the stored period for each security.
- `movement_security_links` connects confirmed OpenDirector movement events to
  a security without silently guessing from similar company names.

The default historical boundary is derived from the database. It is currently
27 September 2021, the date of the earliest stored OpenDirector newsletter.

## Initial and incremental loads

Refresh the official ASX company directory without downloading prices:

```sh
uv run opendirector_prices.py \
  --apply-schema \
  --sync-asx-directory \
  --directory-only \
  --database-config db.conf \
  --stats
```

Apply the curated OpenDirector name mappings and load their full history:

```sh
uv run opendirector_prices.py \
  --seed \
  --mapped-only \
  --database-config db.conf \
  --stats
```

Update only confirmed OpenDirector companies, overlapping the preceding week:

```sh
uv run opendirector_prices.py \
  --mapped-only \
  --incremental \
  --database-config db.conf \
  --stats
```

Slowly backfill the current ASX directory, 25 of the least-current series at a
time:

```sh
uv run opendirector_prices.py \
  --stale-first \
  --limit 25 \
  --incremental \
  --delay-seconds 1 \
  --database-config db.conf \
  --stats
```

Securities without any observations are selected first. After the initial
backfill, the same command rotates through the series whose latest stored
observation is oldest. The one-second delay is applied between Yahoo requests,
not after the final request.

On `raksasa`, this command is run daily at 06:30 Australia/Sydney time by the
`techskills` user crontab. The wrapper uses a non-blocking lock to prevent
overlapping runs and retains timestamped logs for 90 days under
`/home/techskills/jobs/opendirector_prices/logs`.

## Academic-use policy

The initial provider is Yahoo Finance via `yfinance`. These rows use the source
label `yahoo_via_yfinance`. The yfinance project describes the underlying
Yahoo data as intended for personal use, so this is a research collection, not
a redistributable production feed. Keep the raw observations local, retain the
provider and ingestion-run metadata, and publish derived research results
rather than a replica of the underlying price database. Research outputs
should identify Yahoo Finance via `yfinance` as the retrieval route and record
the retrieval period. The schema can retain a licensed provider alongside it.

For a complete historical ASX universe, including companies that delisted
before the current directory snapshot, use licensed ASX historical data or an
ASX-authorized vendor. A current-company download alone creates survivorship
bias.

## Historical directors and executives

The most useful source layers are:

1. **ASX announcements and annual reports.** Appointment, resignation and
   retirement announcements provide event dates. Annual reports provide
   periodic board and senior-management snapshots. ASX ComNews is the
   exchange's complete licensed announcement feed; Morningstar DatAnalysis
   also provides an announcement and annual-report archive.
2. **ASIC historical company extracts.** These provide past and present
   statutory officeholders, particularly directors and company secretaries.
   They are authoritative for Australian registered entities but do not
   generally identify operational executives such as CFOs unless the person
   is also an officeholder.
3. **Morningstar DatAnalysis.** Its Australian listed-company product includes
   corporate history, cross-directorships, committee composition, ASX
   announcements from 1998, annual reports and price history. Institutional or
   university access would be worth checking before purchasing another feed.
4. **LSEG Officers & Directors / BoardEx.** This commercial dataset provides
   executive and director employment histories, committee memberships,
   biographies and compensation. The repository contains older BoardEx-shaped
   tables, but the corresponding raw tables in the live database are empty, so
   they are not currently a historical source.

Macquarie Business School's Finance Decision Lab advertises access to FactSet,
LSEG Workspace and S&P Capital IQ Pro. That is the first institutional-access
route to test for both licensed ASX histories and structured historical
leadership data before buying another subscription. Export and retention still
need to follow the relevant licence terms.

The recommended historical model is event-sourced: retain the source document,
record appointment and cessation events with effective dates, and derive
tenure intervals. Annual-report snapshots can then identify missing events
without being mistaken for exact appointment dates.
