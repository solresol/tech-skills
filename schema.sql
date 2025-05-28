create extension if not exists pg_trgm;

-- Currently not using these

create table board_composition_raw (
       CompanyID varchar,
       DirectorID varchar,
       DirectorName varchar,
       CompanyName varchar,
       RoleName varchar,
       DateStartRole varchar,
       DateEndRole varchar,
       Seniority varchar
);

create table company_details_raw (
       BoardName varchar,
       HOAddress1 varchar,
       HOAddress2 varchar,
       HOAddress3 varchar,
       HOAddress4 varchar,
       HOAddress5 varchar,
       HOCountryName varchar,
       HOTelNumber varchar,
       HOFaxNumber varchar,
       HOURL varchar,
       FinancialURL varchar,
       CompanyPolicy varchar,
       CCAddress1 varchar,
       CCAddress2 varchar,
       CCAddress3 varchar,
       CCAddress4 varchar,
       CCAddress5 varchar,
       CCCountryName varchar,
       CCTelNumber varchar,
       CCFaxNumber varchar,
       CIKCode varchar,
       Sector varchar,
       Index varchar,
       OrgType varchar,
       BoardID varchar,
       Ticker varchar,
       ISIN varchar,
       CountryOfQuote varchar,
       Currency varchar,
       RevenueValueDate varchar,
       MktCapitalisation varchar,
       NoEmployees varchar,
       Revenue varchar,
       AdvisorName varchar,
       AdvTypeDesc varchar
);

create table individual_director_profile_details_raw (
       DirectorName varchar,
       Title varchar,
       Forename1 varchar,
       Forename2 varchar,
       Forename3 varchar,
       Forename4 varchar,
       UsualName varchar,
       Surname varchar,
       SuffixTitle varchar,
       DOB varchar,
       DOD varchar,
       Age varchar,
       Gender varchar,
       Nationality varchar,
       Recreations varchar,
       DirectorVisible varchar,
       DirectorID varchar,
       ClientDirectorID varchar,
       NetworkSize varchar
);

----------------------------------------------------------------------
create table submissions_raw (
 submission jsonb
);
create unique index on submissions_raw (cast(jsonb_extract_path_text(submission, 'cik') as int));

create table vanished_cikcodes (
  cikcode int primary key
);

create table filings (
  cikcode int not null,
  accessionNumber varchar not null,
  filingDate date not null,
  reportDate date,
  acceptanceDateTime timestamp,
  act varchar,
  form varchar,
  fileNumber varchar,
  filmNumber varchar,
  items varchar,
  size int,
  isXBRL boolean,
  isInlineXBRL boolean,
  primaryDocument varchar,
  primaryDocDescription varchar,
  accessionNumberWithoutHyphens varchar
      generated always as (replace(accessionNumber, '-', '')) stored,
  document_storage_url varchar
      generated always as (
	     'https://www.sec.gov/Archives/edgar/data/'
	  || (cikcode :: varchar)
	  || '/'
	  || replace(accessionNumber, '-', '')
	  || '/'
	  || primaryDocument) stored,
  document_url_links_relative_to varchar
      generated always as (
	     'https://www.sec.gov/Archives/edgar/data/'
	  || (cikcode :: varchar)
	  || '/'
	  || replace(accessionNumber, '-', '')) stored,
  primary key (cikcode, accessionNumber)
);
create index on filings(cikcode);
create index on filings(extract(year from filingDate));
create unique index on filings(document_storage_url);
create index on filings(accessionNumber);

create table html_doc_cache (
  url varchar primary key,
  content bytea,
  encoding varchar,
  content_type varchar,
  date_fetch timestamp default current_timestamp
);

create table html_fetch_failures (
  url varchar primary key,
  status_code int,
  date_attempted  timestamp default current_timestamp
);

create table if not exists director_extract_batches (
       id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
       openai_batch_id text,
       when_created timestamp default current_timestamp,
       when_sent timestamp,
       when_retrieved timestamp
);

create table if not exists director_extractions (
       url varchar unique references html_doc_cache(url),
       batch_id int references director_extract_batches(id)
);
create index on director_extractions(batch_id);


 create table if not exists batchprogress (
        batch_id int references director_extract_batches(id), 
        when_checked timestamp default current_timestamp, 
        number_completed int, 
        number_failed int
);

create table if not exists director_extraction_raw (
       cikcode int not null,
       accessionNumber varchar not null,
       response jsonb not null,
       prompt_tokens int,
       completion_tokens int,
       foreign key (cikcode, accessionnumber) references filings(cikcode, accessionnumber),
       primary key (cikcode, accessionnumber)
);


create materialized view director_mentions as SELECT
    cikcode,
    accessionnumber,
    upper(director->>'name') AS director_name,
    (director->>'software_background')::BOOLEAN AS software_background,
    director->>'reason' AS reason,
    director->>'source_excerpt' AS source_excerpt
FROM director_extraction_raw,
     jsonb_array_elements(response->'directors') AS director;



-- create materialized view cik2ticker as select
--    cast(submission->>'cik' as int) as cikcode,
--    submission->>'name' as company_name,
--    tickers.value #>> '{}' as ticker
-- FROM submissions_raw,
--    jsonb_array_elements(submission->'tickers') as tickers;

create view cik2name as select
   distinct cast(submission->>'cik' as int) as cikcode,
   submission->>'name' as company_name
FROM submissions_raw;

create view company_directorships as select
  company_name,
  cik2name.cikcode,
  director_name,
  bool_or(software_background) as software_background,
  min(filingDate) as start_date,
  max(filingDate) as end_date
from filings join cik2name using(cikcode)
     join director_mentions using(accessionnumber)
 group by company_name, cik2name.cikcode, director_name;


--create view
--  extract('year' from filingDate)
-- Schema for storing director compensation, age, role, and committee information

-- Table for tracking extraction batches
CREATE TABLE IF NOT EXISTS director_extract_batches (
    id SERIAL PRIMARY KEY,
    openai_batch_id TEXT,
    when_sent TIMESTAMP,
    when_completed TIMESTAMP
);

-- Table for tracking which URLs have been processed
CREATE TABLE IF NOT EXISTS director_compensation (
    url TEXT PRIMARY KEY,
    batch_id INT REFERENCES director_extract_batches(id),
    processed BOOLEAN DEFAULT FALSE
);

-- Table for storing director information
CREATE TABLE IF NOT EXISTS director_details (
    id SERIAL PRIMARY KEY,
    url TEXT REFERENCES director_compensation(url),
    name TEXT NOT NULL,
    age INT,
    role TEXT,
    compensation INT,
    source_excerpt TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table for storing committee memberships
CREATE TABLE IF NOT EXISTS director_committees (
    id SERIAL PRIMARY KEY,
    director_id INT REFERENCES director_details(id),
    committee_name TEXT NOT NULL,
    UNIQUE(director_id, committee_name)
);

-- Create indexes for faster queries
CREATE INDEX IF NOT EXISTS idx_director_details_url ON director_details(url);
CREATE INDEX IF NOT EXISTS idx_director_details_name ON director_details(name);
CREATE INDEX IF NOT EXISTS idx_director_committees_director_id ON director_committees(director_id);
CREATE INDEX IF NOT EXISTS idx_director_committees_committee_name ON director_committees(committee_name);

-- Create a view to join director details with their committees
CREATE OR REPLACE VIEW director_full_details AS
SELECT
    d.id,
    d.url,
    d.name,
    d.age,
    d.role,
    d.compensation,
    (SELECT array_agg(committee_name) FROM director_committees WHERE director_id = d.id) AS committees,
    d.source_excerpt
FROM
    director_details d;

-- Table to store historical closing prices for U.S. stocks
CREATE TABLE IF NOT EXISTS stock_prices (
    ticker TEXT NOT NULL,
    price_date DATE NOT NULL,
    close_price NUMERIC,
    PRIMARY KEY (ticker, price_date)
);

-- Schema for the CIK to ticker mapping
-- Create a new table for storing cikcode to ticker mappings
CREATE TABLE IF NOT EXISTS cik_to_ticker (
    cikcode INT NOT NULL,
    ticker VARCHAR NOT NULL,
    PRIMARY KEY (cikcode, ticker)
);

-- Create index for faster lookups by ticker
CREATE INDEX IF NOT EXISTS idx_cik_to_ticker_ticker ON cik_to_ticker(ticker);

-- Create index for faster lookups by cikcode
CREATE INDEX IF NOT EXISTS idx_cik_to_ticker_cikcode ON cik_to_ticker(cikcode);

-- Create a view that combines CIK, ticker, and company name information
CREATE OR REPLACE VIEW company_ticker_info AS
SELECT
    c.cikcode,
    c.company_name,
    t.ticker
FROM
    cik2name c
JOIN
    cik_to_ticker t ON c.cikcode = t.cikcode;

-- Create a function to find a company by ticker
CREATE OR REPLACE FUNCTION get_company_by_ticker(ticker_symbol VARCHAR)
RETURNS TABLE (
    cikcode INT,
    company_name VARCHAR,
    ticker VARCHAR
) AS $$
BEGIN
    RETURN QUERY
    SELECT * FROM company_ticker_info
    WHERE UPPER(ticker) = UPPER(ticker_symbol);
END;
$$ LANGUAGE plpgsql;
