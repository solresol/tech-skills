-- The following data was sourced from BoardEx. Somewhere in there,
-- there was data on the composition of the board.

\copy board_composition_raw from 'data/usa/board-composition.csv' header csv
\copy company_details_raw from 'data/usa/company-profile-details.csv' header csv
\copy individual_director_profile_details_raw from 'data/usa/individual-director-profile-details.csv' header csv

create materialized view listed_company_details as
  select distinct BoardName as board_name,
   cast(CIKCode as int) as cikcode,
   Sector,
   cast(BoardID as int) as company_id,
   min(Ticker) as Ticker
   -- Ticker (multiple ticker codes for a single company_id)
   -- I'm not including index, because it should be denormalised. Another day.
 from company_details_raw
 where cikcode is not null
   and ticker is not null
   and hocountryname = 'United States'
   group by BoardName, CIKCode, Sector, BoardID;

create index on listed_company_details(cikcode); -- hmm, cikcodes are not unique?!?!?
create unique index on listed_company_details(company_id);
create index on listed_company_details(ticker); -- ticket codes are not unique?!?!?

create INDEX ON listed_company_details USING GIST(board_name gist_trgm_ops);
create index on listed_company_details(sector);
create INDEX ON listed_company_details USING GIST(sector gist_trgm_ops);



create materialized view board_composition_parsed as
  select
	cast(CompanyID as int) as company_id,
	cast(DirectorID as int) as director_id,
	RoleName,
	to_timestamp(nullif(DateStartRole, 'N'), 'YYYYMMDD') as role_start_date,
	case when DateEndRole = 'C' then null
	     when DateEndRole = 'N' then null
	     else to_timestamp(DateEndRole, 'YYYYMMDD')
	end as role_end_date,
	seniority
   from board_composition_raw
   join listed_company_details on (cast(board_composition_raw.CompanyID as int) = listed_company_details.company_id);



create index on board_composition_parsed(company_id);
create index on board_composition_parsed(director_id);
create index on board_composition_parsed(role_start_date);
create index on board_composition_parsed(role_end_date);

create materialized view board_transition_dates as
 with raw_dates as (
  select company_id, role_start_date as transition_date from board_composition_parsed
    where role_start_date is not null
  union
  select company_id, role_end_date as transition_date from board_composition_parsed
    where role_end_date is not null
    ) select company_id,
	     transition_date,
	     rank() over (partition by company_id order by transition_date)
	      as company_transition_event_number
  from raw_dates;

create unique index on board_transition_dates(company_id, company_transition_event_number);

create materialized view board_composition as
 select board_composition_parsed.company_id, director_id,
	role_start_date,
	commence.company_transition_event_number as role_start_event_number,
	role_end_date,
	finish.company_transition_event_number as role_end_event_number
  from board_composition_parsed
  left join board_transition_dates as commence
	on (commence.company_id = board_composition_parsed.company_id and
	    commence.transition_date = board_composition_parsed.role_start_date)
  left join board_transition_dates as finish
	on (finish.company_id = board_composition_parsed.company_id and
	    finish.transition_date = board_composition_parsed.role_end_date);

create index on board_composition (company_id);
create index on board_composition (director_id);
create index on board_composition (company_id, director_id);
create index on board_composition (company_id, director_id, role_start_event_number);
create index on board_composition (company_id, director_id, role_end_event_number);
create index on board_composition (company_id, director_id, role_start_event_number, role_end_event_number);



create materialized view directors_by_event_number as
  select company_id, director_id, company_transition_event_number
    from board_composition join board_transition_dates using (company_id)
   where (role_start_event_number <= company_transition_event_number
	  or role_start_event_number is null)
	 and
	 (role_end_event_number > company_transition_event_number
	  or role_end_event_number is null);

create index on directors_by_event_number(company_id);
create index on directors_by_event_number(director_id);
create index on directors_by_event_number(company_id, director_id);
create index on directors_by_event_number(company_id, director_id, company_transition_event_number);
create index on directors_by_event_number(company_id, company_transition_event_number);


create materialized view director_overlaps as
  select first.director_id as director1,
	 second.director_id as director2,
	 company_id,
	 min(company_transition_event_number) as first_event_together,
	 max(company_transition_event_number) as last_event_together,
	 count(company_transition_event_number) as number_of_events_together
   from directors_by_event_number as first
   join directors_by_event_number as second
  using (company_id, company_transition_event_number)
  where first.director_id < second.director_id
  group by first.director_id, second.director_id, company_id;

create index on director_overlaps(director1);
create index on director_overlaps(director2);
create index on director_overlaps(director1, director2);


create materialized view individual_director_profile_details as
  select cast(DirectorID as int) as director_id,
	 DirectorName as director_name,
	 Title,
	 Forename1,
	 Forename2,
	 Forename3,
	 Forename4,
	 UsualName,
	 Surname,
	 SuffixTitle,
	 DOB as date_of_birth,
	 DOD as date_of_death,
	 cast(age as int) as age,
	 Gender
	 from individual_director_profile_details_raw;


create materialized view active_directors as
  select company_id, director_id from board_composition where role_end_date is null;
create index on active_directors(company_id);
create index on active_directors(director_id);
create index on active_directors(company_id, director_id);

create materialized view active_multi_directors as
  select director_id, count(distinct company_id) as number_of_directorships
   from active_directors
group by director_id having count(distinct company_id) > 1;
create unique index on active_multi_directors(director_id);

create materialized view company_connectivity as
select
  first.company_id as company1,
  second.company_id as company2,
  count(distinct director_id) as number_of_common_directors
 from active_directors as first join active_directors as second using (director_id)
 where first.company_id < second.company_id
 group by first.company_id, second.company_id;
create index on company_connectivity(company1);
create index on company_connectivity(company2);
create index on company_connectivity(company1, company2);


create view directors_active_on_filing_date as
 select filingDate,accessionnumber,form, cikcode, board_name, company_id, director_id,
 director_name, forename1, surname,
	filingDate - role_start_date as time_already_in_role,
	role_end_date - filingDate as time_left_in_role
   from filings
   join listed_company_details using (cikcode)
   join board_composition using (company_id)
   join individual_director_profile_details using (director_id)
  where (role_start_date < filingDate or role_start_date is null)
    and (role_end_date > filingDate or role_end_date is null);
