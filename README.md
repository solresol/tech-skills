How to run everything
=====================

1. Create a postgresql database, along with a username and password to
store the data into. Set environment variables like PGHOSTNAME,
PGDATABASE and PGUSER (and create a `.pgpass` file) so that you can
run `psql` commands without extra complications.

2. Run `psql -f schema.sql`

3. Download from BoardEx and put them into the `data/usa/` folder:

- `board-composition.csv`
- `company-profile-details.csv`
- `individual-director-profile-details.csv`

(One day I should automate this, but I'm not sure if BoardEx allows it)

4. Run `psql -f etl.sql`

5. Download and put this into `data/usa/`

- https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip

This probably could be automated. Edgar seems to check the user agent.


6. Run `virtualenv .venv` (or whatever equivalent you do to create a virtual python
environment on your operating system)

7. Run `. .venv/bin/activate` (or whatever equivalent is on your operating system).
Feel free to submit a patch here if you are on Windows and you get this working.

8. Create a `db.conf` file with the connection details for your postgresql database.
It should look like:

```
[database]
username=foo
password=hunter2
hostname=mydb-server
port=5432
dbname=tech-skills
```

9. Run `load_listed_company_submissions.py`


10. Run `fetch_forms_from_edgar.py` and `fetch_forms_from_edgar.py --year` _10 years ago_
Or do as I did, and run
```sh
for y in $(seq 2022 -1 2001)
do
   banner $y
   ./fetch_forms_from_edgar.py --progress --year $y
done
```


----------------------------------------------------------------------

The next steps are from a not-very successful attempt to build my own
extraction technology. They are probably safe to ignore.


11. Run `extract_tables.py`

12. Run `table_director_affinity.py`

13. Run `table_deep_analysis.py`

14. Run `every_textual.py`

This will take about a day to run, and it is likely to have many errors and
need to be restarted after it fails. Check the table `filings_with_textual_parse_errors`
to see what it has died on.

15. Review the content of `keywords_to_search_for`

16. Run `refresh materialized view director_mentions;`
Maybe with some clever indexing, I could get this to be able to be refreshed concurrently.

17. Run `python -m spacy download en_core_web_sm`

18. Run `grammar_parse.py`

This will take about 2 months to run, and might take an extremely long time to start.

If you have a lot of spare CPUs (e.g. 8) you can do this...

```sh
./get_cikcodes.py | xargs -n 1 --max-procs 8 --verbose ./grammar_parse.py --random-order --cikcode
```

It also uses up the bulk of the disk space in the database. (99% or higher.)

19. Run `number_sentences.py`

20. `refresh materialized view directors_active_on_filing_date_materialized`

21. Run `pronoun_resolution.py`

21. `refresh materialized view pronoun_usage_over_time;`

----

What I need to do next:

- Extract summary sentences and see what skills they have.

----------------------------------------------------------------------

From here on is the GPT-based approach.

22. (Run this once only; it's not idempotent)

  `prompts/generation2/setup.sh`

23. `naive_sentences.py`

It's nice if you run it in a loop with --progress --stop-after 1000


24. Populate `vocabulary_required_for_prompt`. You'll use the prompt_ID from
step 22 and vocabulary that would have to be in the relevant sections to be
worth bothering with. (We only do this to save the number of OpenAI API calls
we make, because otherwise it becomes expensive).

25. Run `ask_openai_batch.py --prompt generation2`
(Currently broken.)

----------------------------------------------------------------------


(Maybe also...)
- https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip



# Utilities

`get_company.py`

`get_doc.py`

`get_table.py`

`get_cikcodes.py`
