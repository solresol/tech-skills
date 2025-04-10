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
