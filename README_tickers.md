# CIK to Ticker Extractor

This tool extracts ticker information from SEC submission files and populates a database table.

## Setup

1. Make sure you have the submissions.zip file (from https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip)
   stored in your data directory.

2. Set up the database schema:
   ```
   psql -f ticker_schema.sql
   ```

## Running the Extractor

Run the extractor with:
```
python extract_tickers.py --progress --verbose
```

Options:
- `--submissions-zip`: Path to the submissions.zip file (default: data/usa/submissions.zip)
- `--database-config`: Path to the database configuration file (default: db.conf)
- `--schema-file`: Path to the schema SQL file (default: ticker_schema.sql)
- `--progress`: Show a progress bar
- `--verbose`: Show detailed logging information
- `--only-cikcode`: Process only one specific CIK code (for debugging)

## Creating the View

After running the extractor, set up the view for easier querying:
```
psql -f ticker_view.sql
```

## Usage Examples

### Get All Tickers for a CIK
```sql
SELECT ticker FROM cik_to_ticker WHERE cikcode = 1234567;
```

### Get Company Information by Ticker
```sql
SELECT * FROM get_company_by_ticker('AAPL');
```

### Get All Companies with Their Tickers
```sql
SELECT * FROM company_ticker_info ORDER BY company_name;
```