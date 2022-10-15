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

(Maybe also...)
- https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip



