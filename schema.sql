create extension if not exists pg_trgm;

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



-- Doesn't look like I actually created this table
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
create index on table_director_affinity (table_id) where directors_are_column_headers OR directors_are_row_headers;

create table tables_without_mentioned_directors (
  table_id int primary key references filing_tables
);

create table tables_without_content_index (
   table_id int primary key references filing_tables
);

create table table_deep_details (
   table_id int primary key references filing_tables,
   director_index_position int not null, -- e.g. 2 means that there are two irrelevant rows above or two irrelevant columns to the left
   content_index_position int not null -- if directors_are_column_headers then this is a row number
);

create table directors_mentioned_in_table (
   table_id int not null references filing_tables,
   director_id int not null, -- references  individual_director_profile_details
   surname_fragment_used varchar not null,
   index_position_of_director int not null check (index_position_of_director >= 0),
   primary key (table_id, director_id)
);

create table attributes_of_directors_mentioned_in_table (
   table_id int not null references filing_tables,
   index_position int not null,
   attribute_name varchar not null,
   primary key (table_id, index_position)
);

create table low_variance_regions_in_table (
   table_id int not null references filing_tables,
   region_id int not null,
   starting_row int not null,
   ending_row int not null check (ending_row > starting_row),
   distinct_value_count int not null,
   number_of_rows int generated always as (ending_row - starting_row) stored,
   primary key (table_id, region_id)
);
create unique index on low_variance_regions_in_table (table_id, starting_row, ending_row);


create table denormalised_table (
   original_table_id int not null references filing_tables(table_id),
   director_id int not null,
   attribute_index_position int not null,
   attribute_value varchar not null,
   foreign key (original_table_id, director_id) references directors_mentioned_in_table(table_id, director_id),
   foreign key (original_table_id, attribute_index_position) references attributes_of_directors_mentioned_in_table(table_id, index_position)
);




----------------------------------------------------------------------

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

----------------------------------------------------------------------

create table filings_with_textual_parse_errors (
  cikcode int not null,
  accessionNumber varchar not null,
  errors varchar not null,
  FOREIGN KEY (cikcode, accessionnumber) references filings (cikcode, accessionnumber)
);

create table filings_parsed_successfully (
  cikcode int not null,
  accessionNumber varchar not null,
  when_parsed timestamp default current_timestamp,
  FOREIGN KEY (cikcode, accessionnumber) references filings (cikcode, accessionnumber)
);

create table document_headings (
  cikcode int not null,
  accessionNumber varchar not null,
  heading_level int,
  heading_text varchar,
  document_position int,
  PRIMARY KEY (cikcode, accessionnumber, document_position),
  FOREIGN KEY (cikcode, accessionnumber) references filings (cikcode, accessionnumber)
);
create index on document_headings using gin(heading_text gin_trgm_ops);

create table document_table_positions (
  cikcode int not null,
  accessionNumber varchar not null,
  table_number int,
  document_position int,
  PRIMARY KEY (cikcode, accessionnumber, document_position),
  FOREIGN KEY (cikcode, accessionnumber) references filings (cikcode, accessionnumber)
);
create unique index on document_table_positions(cikcode, accessionNumber, table_number);

create table document_text_positions (
   cikcode int not null,
   accessionNumber varchar not null,
   document_position int not null,
   position_of_leader int,
   plaintext varchar,
  PRIMARY KEY (cikcode, accessionnumber, document_position),
  FOREIGN KEY (cikcode, accessionnumber) references filings (cikcode, accessionnumber)
);
create index on document_text_positions using gin(plaintext gin_trgm_ops);

create table spacy_parses (
   cikcode int not null,
   accessionNumber varchar not null,
   document_position int not null,
   spacy_blob bytea not null,
   parse_time timestamp default current_timestamp,
   foreign key (cikcode, accessionnumber, document_position) references document_text_positions(cikcode, accessionnumber, document_position)
);
create index on spacy_parses(parse_time); -- so that it is possible to report on progress

create table sentences (
   sentence_id bigserial primary key,
   cikcode int not null,
   accessionNumber varchar not null,
   document_position int not null,
   sentence_number_within_fragment int not null,
   sentence_text varchar not null,
   foreign key (cikcode, accessionnumber, document_position) references document_text_positions(cikcode, accessionnumber, document_position)
);
create index on sentences using gin(sentence_text gin_trgm_ops);


create view sentences_within_document as
  select cikcode, accessionNumber,
	 rank() over (order by document_position, sentence_number_within_fragment)
	    as sentence_number_within_document,
	 sentence_id
    from sentences;


create table named_entities (
   sentence_id bigint not null references sentences,
   named_entity varchar not null,
   label varchar not null,
   primary key (sentence_id, named_entity, label)
);
create index on named_entities(label);


create table noun_chunks (
   sentence_id bigint not null references sentences,
   noun_chunk varchar not null,
   repeat_count int not null,
   primary key (sentence_id, noun_chunk)
);

create table pronouns (
   sentence_id bigint not null references sentences,
   pronoun varchar not null,
   tag varchar not null,
   repeat_count int not null,
   primary key (sentence_id, pronoun, tag)
);
create index on pronouns (upper(pronoun));


create view document_position_predecessors as
  select cikcode,
         accessionnumber,
	 parent.document_position,
         child.document_position as predecessor_document_position
   from document_text_positions as parent
   join document_text_positions as child
   using (cikcode, accessionnumber)
   where child.document_position >= parent.position_of_leader
     and child.document_position <= parent.document_position;

create view sentence_predecessors as
  select parent.sentence_id,
         child.sentence_id as predecessor_sentence
    from sentences as parent
    join document_text_positions as dtp_parent using (accessionnumber, cikcode, document_position)
    join document_position_predecessors using (accessionnumber, cikcode, document_position)
    join document_text_positions as dtp_child on
          (document_position_predecessors.cikcode = dtp_child.cikcode and
	  document_position_predecessors.accessionnumber = dtp_child.accessionnumber and
	  document_position_predecessors.predecessor_document_position = dtp_child.document_position)
    join sentences as child on (
        dtp_child.accessionnumber = child.accessionnumber and
	dtp_child.cikcode = child.cikcode and
	dtp_child.document_position = child.document_position
	)
   where (
          (child.document_position < parent.document_position) or
	  (child.sentence_number_within_fragment <= parent.sentence_number_within_fragment)
	  );
	

    
create view director_sentence_references as
 select directors_active_on_filing_date.cikcode,
        directors_active_on_filing_date.accessionnumber,
        document_position,
	sentence_number_within_fragment,
--	sentence_number_within_document,
	sentence_id,
	sentence_text,
	named_entity,
        director_id,
	company_id,
	director_name,
	surname
   from
    directors_active_on_filing_date
   join
    document_text_positions using (cikcode, accessionnumber)
   join
     sentences using (cikcode, accessionnumber, document_position)
--   join 
--     sentences_within_document using (sentence_id)
   join named_entities using (sentence_id)
   where named_entity ilike '%' || surname || '%'
     and label = 'PERSON';


-- create view pronoun_antecedents as 
--     select named_entities.sentence_id as predecessor_sentence,
--            sentence_predecessors.sentence_id as sentence_id,
-- 	   named_entity,
-- 	   s1.sentence_text as predecessor_text,
-- 	   s2.sentence_text as referrant_text,
-- 	   rank() over (partition by s2.cikcode, s2.accessionnumber order by s2.document_position desc, s2.sentence_number_within_fragment desc)
--       from named_entities
--       join sentence_predecessors on (named_entities.sentence_id = sentence_predecessors.predecessor_sentence)
--       join sentences as s1 on (named_entities.sentence_id = s1.sentence_id)
--       join  sentences as s2 on (sentence_predecessors.sentence_id = s2.sentence_id)
--       where label = 'PERSON';



create view pronoun_antecedents as 
    select named_entities.sentence_id as predecessor_sentence,
           sentence_predecessors.sentence_id as sentence_id,
	   named_entity
      from named_entities
      join sentence_predecessors on (named_entities.sentence_id = sentence_predecessors.predecessor_sentence)
      where label = 'PERSON';
      
      --and sentence_predecessors.sentence_id = 52832;

create view pronoun_antecedent_horrifically_slow as
 with unfiltered_antecedents as (
  select pronouns.sentence_id,
         sentence_predecessors.predecessor_sentence,
         pronoun,
	 tag,
	 named_entity,
	 company_id,
	 director_id,
	 director_name,
	 surname,
	 s1.sentence_text as sentence_text,
	 s2.sentence_text as predecessor_text,
	 rank() over (partition by s2.cikcode, s2.accessionnumber order by s2.document_position desc, s2.sentence_number_within_fragment desc) as reference_distance
   from pronouns
   join sentences s1 using (sentence_id)
   join sentence_predecessors using (sentence_id)
   join sentences s2 on (sentence_predecessors.predecessor_sentence = s2.sentence_id)
   join director_sentence_references on (director_sentence_references.sentence_id = sentence_predecessors.predecessor_sentence)
 ) select * from unfiltered_antecedents where reference_distance = 1;


-- ,
--    has_single_director_mention boolean not null,
--    has_pronoun_mention boolean not null,
--    coreference_sentence bigint references sentences(sentence_id),
--    director_id int,
--    director_name varchar,

-- );



   
----------------------------------------------------------------------

create table keywords_to_search_for (
  keyword varchar primary key
);
insert into keywords_to_search_for (keyword) values ('mathematics');
insert into keywords_to_search_for (keyword) values ('maths');
insert into keywords_to_search_for (keyword) values ('engineering');
insert into keywords_to_search_for (keyword) values ('cybersecurity');
insert into keywords_to_search_for (keyword) values ('cyber security');
insert into keywords_to_search_for (keyword) values ('cyber-security');
insert into keywords_to_search_for (keyword) values ('computer science');
insert into keywords_to_search_for (keyword) values ('compsci');


create materialized view director_mentions as
  select keyword, filingdate, cikcode, accessionnumber, board_name, company_id, director_id,
   director_name, forename1, surname, document_position, plaintext
   from directors_active_on_filing_date join document_text_positions using (cikcode, accessionnumber),
   keywords_to_search_for
   where plaintext like ('%' || surname || '%')
     and plaintext ilike ('%' || keyword || '%');
create index on director_mentions(director_id);
create index on director_mentions(surname);
create index on director_mentions(company_id);
create index on director_mentions(board_name);
create index on director_mentions(keyword);
create index on director_mentions(director_id, keyword);
-- create unique index on director_mentions(director_id, keyword, cikcode, accessionnumber, document_position);
-- commented out, but why are we getting duplicates?
-- not quite right, needs to go down to the sentence level

----------------------------------------------------------------------

create view sentences_mentioning_keywords as
  select sentence_id, sentence_text, keyword
    from sentences, keywords_to_search_for
     where sentence_text ilike '%' || keyword || '%';
     

----------------------------------------------------------------------
-- Funny stuff

create materialized view pronoun_usage_over_time as 
select upper(pronoun) as pronoun,
       extract(year from filingdate) as year,
       case
        when upper(pronoun) in ('HE', 'HIM', 'HIS', 'HIMSELF') then 'male'
        when upper(pronoun) in ('SHE', 'HER', 'HERSELF') then 'female'
	else null
       end as pronoun_gender,
       count(*) as number_of_uses
  from pronouns
  join sentences using (sentence_id)
  join filings using (cikcode, accessionnumber)
  group by 1, 2, 3
  ;

create view pronoun_pivot_table as
 with male as (
    select year, sum(number_of_uses) as number_of_uses from pronoun_usage_over_time
       where pronoun_gender = 'male' group by year
    ),
    female as (
    select year, sum(number_of_uses) as number_of_uses from pronoun_usage_over_time
       where pronoun_gender = 'female' group by year
    )
  select year,
         male.number_of_uses as male_usage_count,
	 female.number_of_uses as female_usage_count,
	 male.number_of_uses / (1.0 * female.number_of_uses) as male_to_female_ratio
    from male
    join female
    using (year);    

create view pronoun_behaviour as
  select regr_slope(male_to_female_ratio, year) as trend_over_time
   from pronoun_pivot_table;
