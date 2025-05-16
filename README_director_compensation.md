# Director Compensation Extraction Tool

This tool extracts director compensation, age, role, and committee memberships from SEC filings (DEF 14A) and stores the data in a PostgreSQL database.

## Setup

1. Install the required database schema:

```bash
psql -f director_compensation_schema.sql
```

2. Ensure you have an OpenAI API key in `~/.openai.key` (or specify a different location with `--openai-key-file`)

## Usage

### 1. Extract Director Information

The extraction process has two steps:
1. Submit filings to OpenAI for analysis
2. Process the results from OpenAI

#### Step 1: Submit filings to OpenAI

```bash
./extract_director_compensation.py [options]
```

Options:
- `--database-config DB_CONFIG`: Database connection config (default: db.conf)
- `--progress`: Show a progress bar
- `--verbose`: Show detailed logging
- `--stop-after NUM`: Process only NUM documents
- `--cikcode CIK`: Only process documents from a specific CIK code
- `--accession-number ACC_NUM`: Only process a specific accession number
- `--accession-file FILE`: Process a list of accession numbers from a file (one per line)
- `--openai-key-file KEY_FILE`: Path to OpenAI API key file (default: ~/.openai.key)
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

#### Step 2: Process OpenAI results

Once the OpenAI batch processing is complete, retrieve and store the results:

```bash
./process_director_compensation.py [options]
```

Options:
- `--database-config DB_CONFIG`: Database connection config (default: db.conf)
- `--openai-key-file KEY_FILE`: Path to OpenAI API key file (default: ~/.openai.key)
- `--verbose`: Show detailed logging
- `--show-costs`: Display token usage and estimated costs

Example:
```bash
./process_director_compensation.py --verbose --show-costs
```

### Querying the Results

After processing, you can query the database to get director information:

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

## Data Structure

The system uses the following tables:

1. `director_extract_batches`: Tracks OpenAI batch processing
2. `director_compensation`: Tracks which URLs have been processed
3. `director_details`: Stores director information (name, age, role, compensation)
4. `director_committees`: Stores committee memberships for each director

A view `director_compensation_summary` provides an easy way to access combined data including company information.

## Requirements

- Python 3.6+
- PostgreSQL
- OpenAI API access
- BeautifulSoup, psycopg2, and other dependencies in requirements.txt