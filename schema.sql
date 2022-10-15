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



create table edgar_def14a_raw (
  edgar_raw_ref serial primary key,
  cikcode varchar,
  accessionNumber varchar,
  primaryDocument varchar,
  reportDate varchar,
  document text,
);
create index on edgar_def14a_raw(cikcode);
create index on edgar_def14a_raw(cikcode, reportDate);
create index on edgar_def14a_raw(reportDate);


create table filings_with_no_tables (
  cikcode integer,
  accessionnumber varchar,
  FOREIGN KEY (cikcode, accessionnumber) references filings (cikcode, accessionnumber)
);
create unique index on filings_with_no_tables(cikcode, accessionnumber);


create table filing_tables (
  table_id serial primary key,
  cikcode integer,
  accessionnumber varchar,
  table_number int,
  html text,
  FOREIGN KEY (cikcode, accessionnumber) references filings (cikcode, accessionnumber)
);
create unique index on filing_tables(cikcode, accessionnumber, table_number);

create view filings_needing_table_extraction as
  select distinct
	   filings.cikcode,
	   filings.accessionnumber,
	   filings.document_storage_url
      from filings left join filings_with_no_tables using (cikcode, accessionnumber)
		   left join filing_tables using (cikcode, accessionnumber)
  where filings_with_no_tables.cikcode is null
    and filing_tables.cikcode is null;


create table table_director_affinity (
  table_id int primary key references filing_tables,
  number_of_columns int,
  number_of_rows int,
  max_director_names_mentioned_in_any_row int,
  max_director_names_mentioned_in_any_column int,
  number_of_distinct_relevant_director_surnames int,
  max_director_mentions int generated always as (greatest(max_director_names_mentioned_in_any_row, max_director_names_mentioned_in_any_column)) stored,
  directors_are_column_headers boolean generated always as (max_director_names_mentioned_in_any_row > max_director_names_mentioned_in_any_column) stored,
  directors_are_row_headers boolean generated always as (max_director_names_mentioned_in_any_row < max_director_names_mentioned_in_any_column) stored
);

create view tables_with_strongest_director_name_affinity as
with ranked_director_mentions as
(select table_id, cikcode, accessionnumber, table_number,
  max_director_mentions,
  rank() over (partition by cikcode, accessionnumber order by max_director_mentions desc)
     as max_director_mentions_rank,
  number_of_distinct_relevant_director_surnames,
  directors_are_column_headers,
  directors_are_row_headers
 from table_director_affinity join filing_tables using (table_id))
select * from ranked_director_mentions
 where max_director_mentions_rank = 1
 order by cikcode, accessionnumber, table_number;
