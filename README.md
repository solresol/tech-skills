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

[edgar]
useragent="Greg Smith greg@example.com"
```

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


11. Run `uv run ask_openai_batch.py --stop-at 100`

I haven't figured out how to make sure the batches aren't too big or too small. I'm just
winging it by finding a number that seems reasonable.

That should probably be in a cron job.

12. See how the batches are going with `uv run batchcheck.py`

----------------------------------------------------------------------


(Maybe also...)
- https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip



# Utilities

These might or might not still work

`get_company.py`

`get_doc.py`

`get_table.py`

`get_cikcodes.py`
