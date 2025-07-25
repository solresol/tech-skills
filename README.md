How to run everything
=====================

1. Create a postgresql database, along with a username and password to
store the data into. Set environment variables like PGHOSTNAME,
PGDATABASE and PGUSER (and create a `.pgpass` file) so that you can
run `psql` commands without extra complications.

2. Run `psql -f schema.sql`

[PREVIOUSLY I DID THIS... BUT NOW I THINK I NEED TO BUILD A BOARDEX EQUIVALENT TO BE UP-TO-DATE]
3. Download from BoardEx and put them into the `data/usa/` folder:

- `board-composition.csv`
- `company-profile-details.csv`
- `individual-director-profile-details.csv`

(One day I should automate this, but I'm not sure if BoardEx allows it)

[LIKEWISE, I DON'T RUN THIS ANY MORE]
4. Run `psql -f etl.sql`

5. Download and put this into `data/usa/`

- https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip

This probably could be automated. Edgar seems to check the user agent.


8. Create a `db.conf` file with the connection details for your postgresql database.
It should look like:

```
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
useragent="Greg Smith greg@example.com"
```
The `[minified]` section defines a temporary database used for creating sanitized dumps.

9. Run `uv run load_listed_company_submissions.py --progress`


10. Run `fetch_forms_from_edgar.py` and `fetch_forms_from_edgar.py --year` _10 years ago_
Or do as I did, and run
```sh
for y in $(seq 2022 -1 2001)
do
   banner $y
   ./fetch_forms_from_edgar.py --progress --year $y
done
```


11.  Schedule `morningcron.sh`

That will run `uv run ask_openai_batch.py --stop-after 100`,
`uv run extract_director_compensation.py --stop-after 110` and
`uv run fetch_all_sectors.py --stop-after 500 --progress` to gradually
populate the sector table.

I haven't figured out how to make sure the batches aren't too big or too small. I'm just
winging it by finding a number that seems reasonable.


12. See how the batches are going with `uv run batchcheck.py`

Maybe that should be an hourly cron or something

13. Schedule `evenincron.sh`

That will download the results with `uv run batchfetch.py --report-costs`
and then run `uv run boards_website_generator.py` and `rsync` it to
merah

----------------------------------------------------------------------


(Maybe also...)
- https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip


# To-do

Get company share price on the day of their filing, and compare it
to the following year(s).

Look at the quantity of text in a filing and see if it has any 
relationship to the following year(s).

Look at Herdan's law and Zipf's law on the texts and see if the
complexity of language shows anything.

Can we predict high-level fraud from the filings?


# Utilities

These might or might not still work

`get_company.py`

`get_doc.py`

`get_table.py`

`get_cikcodes.py`


# Build the website

`uv run boards_website_generator.py`

This command now also produces a `network.html` page and an accompanying
`network_data.json` file. These visualise connections between companies
that share directors using NetworkX for analysis and D3 for display.

## CIK to Ticker Extractor

This tool extracts ticker information from SEC submission files and populates a
database table.

### Setup
1. Make sure you have the `submissions.zip` file (from <https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip>)
   stored in your `data` directory.
2. Set up the database schema:
   ```
   psql -f schema.sql
   ```

### Running the Extractor
Run the extractor with:
```
python extract_tickers.py --progress --verbose
```
Options:
- `--submissions-zip`: Path to the submissions.zip file (default: `data/usa/submissions.zip`)
- `--database-config`: Path to the database configuration file (default: `db.conf`)
- `--schema-file`: Path to the schema SQL file (default: `schema.sql`)
- `--progress`: Show a progress bar
- `--verbose`: Show detailed logging information
- `--only-cikcode`: Process only one specific CIK code (for debugging)

The schema also creates a view `company_ticker_info` (now including a `sector`
column) and a helper function `get_company_by_ticker` for easier querying.

### Usage Examples
```sql
SELECT ticker FROM cik_to_ticker WHERE cikcode = 1234567;

SELECT * FROM get_company_by_ticker('AAPL');

SELECT * FROM company_ticker_info ORDER BY company_name;
```

## Stock Price Fetcher

This repository includes a small tool for retrieving the closing price of a
U.S. stock ticker for a specific date. The information is stored in a
`stock_prices` table so subsequent requests can be served from the database.

### Setup
1. Ensure a PostgreSQL database is available and a `db.conf` file describes how
   to connect to it (see other scripts in this repo for the format).
2. Install the Python dependency `yfinance` for retrieving stock prices:
   ```bash
   pip install yfinance
   ```
3. Create the table by executing:
   ```bash
   psql -f schema.sql
   ```

### Usage
Run the script with a ticker symbol and a date in `YYYY-MM-DD` format:
```bash
python stock_price.py AAPL 2024-05-10
```
The script outputs the closing price and stores it in the database. Use
`--force` to refetch a price even if it already exists, or `--dummy-run` to
avoid storing the result.

To populate prices for many processed DEF 14A filings in bulk, run:
```bash
./fetch_prices_for_director_filings.py --stop-after 200
```
Any ticker/date combination that can't be retrieved is recorded in the
`stock_price_failures` table. A normal run skips these failures. Passing
`--force` removes a prior failure entry and attempts the download again.

### Fetching Sector Information

You can use `yfinance` to look up the industry sector for a ticker and store it
in the `ticker_sector` table. The script automatically creates the table if it
is missing. Run:

```bash
./fetch_sector.py AAPL
```

Use `--force` to refresh an existing entry or `--dummy-run` to skip inserting
into the database.

To populate sectors for every ticker in `cik_to_ticker`, run `fetch_all_sectors.py`.
It supports `--stop-after` and `--progress` to throttle requests:

```bash
./fetch_all_sectors.py --stop-after 500 --progress
```

## Director Compensation Extraction Tool

This tool extracts director compensation, age, role, and committee memberships
from SEC filings (DEF 14A) and stores the data in a PostgreSQL database.

### Setup

1. Install the required database schema:
   ```bash
   psql -f schema.sql
   ```
2. Ensure you have an OpenAI API key in `~/.openai.key` (or specify a different
   location with `--openai-key-file`).

### Usage

#### 1. Extract Director Information
The extraction process has two steps:
1. Submit filings to OpenAI for analysis
2. Process the results from OpenAI

##### Step 1: Submit filings to OpenAI
```bash
./extract_director_compensation.py [options]
```
Options:
- `--database-config DB_CONFIG`: Database connection config (default: `db.conf`)
- `--progress`: Show a progress bar
- `--verbose`: Show detailed logging
- `--stop-after NUM`: Process only NUM documents
- `--cikcode CIK`: Only process documents from a specific CIK code
- `--accession-number ACC_NUM`: Only process a specific accession number
- `--accession-file FILE`: Process accession numbers from a file
- `--openai-key-file KEY_FILE`: Path to OpenAI API key file (default: `~/.openai.key`)
- `--dry-run`: Don't send anything to OpenAI (for testing)
- `--batch-file FILE`: Where to save the batch file (default: random temp file)
- `--batch-id-save-file FILE`: Save the batch ID to a file

Example:
```bash
# Process a specific company's filing
./extract_director_compensation.py --cikcode 1018724

# Process a list of accession numbers
./extract_director_compensation.py --accession-file my_accessions.txt --progress
```

##### Step 2: Process OpenAI results
Once the OpenAI batch processing is complete, retrieve and store the results:
```bash
./process_director_compensation.py [options]
```
Options:
- `--database-config DB_CONFIG`: Database connection config (default: `db.conf`)
- `--openai-key-file KEY_FILE`: Path to OpenAI API key file (default: `~/.openai.key`)
- `--verbose`: Show detailed logging
- `--show-costs`: Display token usage and estimated costs

Example:
```bash
./process_director_compensation.py --verbose --show-costs
```

### Querying the Results
```sql
-- Get summary of all directors with their compensation and committees
SELECT * FROM director_compensation_summary;

-- Get directors with highest compensation
SELECT name, role, compensation
FROM director_details
ORDER BY compensation DESC
LIMIT 10;

-- Get directors serving on specific committees
SELECT dd.name, dd.role, dd.compensation
FROM director_details dd
JOIN director_committees dc ON dd.id = dc.director_id
WHERE dc.committee_name ILIKE '%audit%';
```

The schema creates several tables including `director_extract_batches`,
`director_compensation`, `director_details`, and `director_committees`, plus a
view `director_compensation_summary` for easy access to combined data.

## Sandbox Setup

To create a sandbox environment with a populated database you can run:

```bash
./envsetup.sh
```

This installs PostgreSQL, downloads the Python dependencies via `uv run uvbootstrap.py`, creates a local `techskills` database and user, writes a `db.conf` file (including a `[minified]` section used for generating sanitized dumps), and restores the latest minified dump from <http://datadumps.ifost.org.au/tech-skills/techskills.sql.gz>.

