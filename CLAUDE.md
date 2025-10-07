# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a data analysis project that extracts and analyzes director information from SEC DEF 14A filings. It downloads SEC filings, processes them using OpenAI's batch API to extract director compensation, age, role, gender, and committee memberships, then generates a static website visualizing the data.

## Development Setup

### Initial Environment Setup

```bash
./envsetup.sh
```

This installs PostgreSQL, Python dependencies via `uv`, creates a local database, and restores a sanitized data dump.

### Database Configuration

Create a `db.conf` file with PostgreSQL connection details:

```ini
[database]
user=foo
password=hunter2
hostname=mydb-server
port=5432
dbname=tech-skills

[minified]
user=foo
password=hunter2
hostname=mydb-server
port=5432
dbname=techskills_min

[edgar]
useragent="Your Name your@email.com"
```

The `[minified]` section is for creating sanitized dumps. The `[edgar]` section is required for SEC API compliance.

### Python Package Manager

This project uses `uv` for dependency management. Run Python scripts with:

```bash
uv run script_name.py [args]
```

Dependencies are in `pyproject.toml` and locked in `uv.lock`.

### Testing

Run tests with:

```bash
uv run python -m pytest tests/
```

The codebase includes mock database and yfinance modules (`mock_psycopg2/`, `yfinance_stub/`) for testing without external dependencies.

## Common Development Commands

### Database Schema

```bash
psql -f schema.sql
```

### Data Pipeline

**Download SEC submissions data:**
```bash
uv run load_listed_company_submissions.py --progress
```

**Fetch DEF 14A forms from SEC:**
```bash
uv run fetch_forms_from_edgar.py --progress --year 2023
```

**Submit filings to OpenAI for director extraction:**
```bash
uv run extract_director_compensation.py --stop-after 100 --progress
```

**Retrieve and process OpenAI batch results:**
```bash
uv run batchfetch.py --show-costs
uv run process_director_compensation.py --show-costs
```

**Check batch processing status:**
```bash
uv run batchcheck.py
```

**Fetch stock prices for processed filings:**
```bash
uv run fetch_prices_for_director_filings.py --stop-after 200
```

**Fetch sector information:**
```bash
uv run fetch_all_sectors.py --stop-after 500 --progress
```

**Generate static website:**
```bash
uv run boards_website_generator.py
```

### Utility Scripts

**Extract ticker symbols:**
```bash
uv run extract_tickers.py --progress --verbose
```

**Fetch stock price for a specific date:**
```bash
uv run stock_price.py AAPL 2024-05-10
```

**Fetch sector for a ticker:**
```bash
uv run fetch_sector.py AAPL
```

**Test database connection:**
```bash
uv run pgconnect.py --database-config db.conf
```

## Code Architecture

### Database Layer

- **pgconnect.py**: Database connection module with mock support for sandboxes (set `SANDBOX_HAS_DATABASE=no` to use mocks)
- **schema.sql**: Complete database schema including tables for filings, director extractions, stock prices, and ticker mappings

### Data Extraction Pipeline

The pipeline has distinct stages:

1. **SEC Data Collection** (`load_listed_company_submissions.py`, `fetch_forms_from_edgar.py`):
   - Downloads company submissions and DEF 14A forms
   - Stores HTML content in `html_doc_cache` table
   - Respects SEC rate limits (1 second delay between requests)

2. **OpenAI Batch Processing** (`extract_director_compensation.py`, `batchfetch.py`):
   - Cleans HTML (removes CSS/JS, invisible elements)
   - Submits to OpenAI Batch API using function calling
   - Uses `director_extract_batches` table to track batch lifecycle
   - Model: `gpt-4.1-mini` (batch)

3. **Result Processing** (`process_director_compensation.py`):
   - Retrieves completed batches
   - Stores structured data in `director_extraction_raw`, `director_details`, `director_committees`
   - Refreshes materialized view `director_mentions`
   - Handles malformed JSON and null characters

4. **Data Enrichment** (`fetch_prices_for_director_filings.py`, `fetch_all_sectors.py`):
   - Fetches stock prices using yfinance
   - Populates `stock_prices` and `ticker_sector` tables
   - Tracks failures in `stock_price_failures` table

### Website Generation

- **boards_website_generator.py**: Creates static website with Jinja2 templates
  - Company pages with director listings
  - Director pages with board memberships
  - Network visualization using NetworkX and D3.js
  - Outputs to `boards-website/` directory

### Automated Workflows

**Morning cron** (`morningcron.sh`):
- Submits new batches to OpenAI
- Extracts director compensation
- Populates sector information

**Evening cron** (`eveningcron.sh`):
- Fetches batch results
- Processes director compensation
- Updates stock prices
- Regenerates website
- Creates weekly database dumps (Sundays)

### Key Database Tables

- `filings`: All SEC filings with generated URLs
- `html_doc_cache`: Cached HTML content from SEC
- `director_extract_batches`: Tracks OpenAI batch lifecycle
- `director_extraction_raw`: Raw JSON responses from OpenAI
- `director_details`: Normalized director information
- `director_committees`: Director committee memberships
- `director_mentions`: Materialized view of all director mentions
- `company_directorships`: View aggregating directors by company
- `cik_to_ticker`: CIK code to ticker symbol mappings
- `company_ticker_info`: View combining company info with sectors

### OpenAI Integration

The project uses OpenAI's Batch API with function calling:

- Function name: `show_director_details`
- Extracts: name, age, role, gender, committees, compensation, source excerpt
- 24-hour completion window
- Tracks batches with local IDs and OpenAI batch IDs
- Metadata includes local batch ID for cross-referencing

### Testing Strategy

- Mock modules for database (`mock_psycopg2`) and yfinance (`yfinance_stub`)
- Environment variables: `SANDBOX_HAS_DATABASE=no`, `USE_YFINANCE_STUB=1`
- Tests use subprocess to run scripts in isolated environments

## Important Notes

- Always include User-Agent when accessing SEC (set in `db.conf` under `[edgar]`)
- Rate limit SEC requests to 1 second between calls
- OpenAI API key stored in `~/.openai.key` (expanduser path)
- The `--stop-after` flag limits processing for incremental runs
- Use `--dry-run` flags to test without committing changes
- Director name normalization is a known issue (see `encode_director_name()` in boards_website_generator.py:28)
