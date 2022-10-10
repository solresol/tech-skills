#!/usr/bin/env python3

import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--submissions-zip",
                    help="Where you downloaded https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip to. (One day this program will fetch it itself)",
                    default="data/usa/submissions.zip"
                    )
parser.add_argument("--database-config",
                    default="db.conf",
                    help="Parameters to connect to the database")
parser.add_argument("--progress",
                    action="store_true",
                    help="Show a progress bar")
parser.add_argument("--only-cikcode",
                    type=int,
                    help="Only process one cikcode (for debugging)")
parser.add_argument("--verbose",
                    action="store_true",
                    help="Lots of debugging messages")

args = parser.parse_args()


import psycopg2.extras
import zipfile
import pgconnect
import logging
import json


if args.verbose:
    logging.basicConfig(
        format='%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s',
        level=logging.INFO,
        datefmt='%Y-%m-%d %H:%M:%S')
    logging.info("Starting")

submissions = zipfile.ZipFile(args.submissions_zip)
conn = pgconnect.connect(args.database_config)
read_cursor = conn.cursor()
write_cursor = conn.cursor()

filing_columns = ['accessionNumber', 'filingDate', 'reportDate', 'acceptanceDateTime', 'act', 'form', 'fileNumber', 'filmNumber', 'items', 'size', 'isXBRL', 'isInlineXBRL', 'primaryDocument', 'primaryDocDescription']
insertion_query = """
insert into filings
   (cikcode,
    accessionNumber,
    filingDate,
    reportDate,
    acceptanceDateTime,
    act,
    form,
    fileNumber,
    filmNumber,
    items,
    size,
    isXBRL,
    isInlineXBRL,
    primaryDocument,
    primaryDocDescription) values (
     %s,%s,%s,
     nullif(%s, '') :: date,
     nullif(%s, '') :: date,
     %s,%s,%s,%s,%s,%s,
     %s :: boolean,
     %s :: boolean,
     %s,%s
    )
    on conflict on constraint filings_pkey do update set
    filingDate = %s,
    reportDate = nullif(%s, '') :: date,
    acceptanceDateTime = nullif(%s, '') :: date,
    act = %s,
    form = %s,
    fileNumber = %s,
    filmNumber = %s,
    items = %s,
    size = %s,
    isXBRL = %s :: boolean,
    isInlineXBRL = %s :: boolean,
    primaryDocument = %s,
    primaryDocDescription = %s
   """

if args.only_cikcode:
    read_cursor.execute("select distinct cikcode from listed_company_details where cikcode = %s", [args.only_cikcode])
else:
    read_cursor.execute("select distinct cikcode from listed_company_details")

if args.progress:
    import tqdm
    iterator = tqdm.tqdm(read_cursor, total=read_cursor.rowcount)
else:
    iterator = read_cursor

for row in iterator:
    cikcode = row[0]
    try:
        source_data = submissions.read(f"CIK{cikcode:010d}.json")
    except KeyError:
        logging.error(f"Missing data for cikcode = {cikcode}")
        write_cursor.execute("insert into vanished_cikcodes (cikcode) values (%s) on conflict do nothing", [cikcode])
        conn.commit()
        continue
    json_data = json.loads(source_data)
    data = psycopg2.extras.Json(json_data)
    write_cursor.execute("select count(*) from submissions_raw where jsonb_extract_path_text(submission,'cik') :: int = %s ", [cikcode])
    c = write_cursor.fetchone()
    if c is None:
        logging.critical(f"Cannot even count the number of submissions with cikcode = {cikcode}")
        continue
    if c[0] == 0:
        logging.info(f"cikcode {cikcode} is new")
        write_cursor.execute("insert into submissions_raw(submission) values (%s)", [data])
    else:
        logging.info(f"Updating existing cikcode {cikcode}")
        write_cursor.execute("update submissions_raw set submission = %s where jsonb_extract_path_text(submission,'cik') :: int = %s", [data, cikcode])
    # Store the filing information in a separate table
    logging.info(f"Cikcode = {cikcode} has {len(json_data['filings']['recent']['accessionNumber'])} rows")
    for i in range(len(json_data['filings']['recent']['accessionNumber'])):
        def get_column(x):
            column = json_data['filings']['recent'][x]
            if i < len(column):
                return column[i]
            else:
                return None
        if get_column('accessionNumber') is None:
            continue
        insert_data = [cikcode] + [get_column(x) for x in filing_columns]
        update_data = [get_column(x) for x in filing_columns[1:]]
        #+ [cikcode, json_data['filings']['recent']['accessionNumber'][i]]
        write_cursor.execute(insertion_query, insert_data + update_data)
    conn.commit()
