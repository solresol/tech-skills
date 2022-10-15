#!/usr/bin/env python3

import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--database-config",
                    default="db.conf",
                    help="Parameters to connect to the database")
parser.add_argument("--progress",
                    action="store_true",
                    help="Show a progress bar")
parser.add_argument("--verbose",
                    action="store_true",
                    help="Lots of debugging messages")
parser.add_argument("--stop-after",
                    type=int,
                    help="Don't try to extract tables from every document. Stop after this number")
args = parser.parse_args()

import pgconnect
import logging
from bs4 import BeautifulSoup

if args.verbose:
    logging.basicConfig(
        format='%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s',
        level=logging.INFO,
        datefmt='%Y-%m-%d %H:%M:%S')
    logging.info("Starting")

conn = pgconnect.connect(args.database_config)
read_cursor = conn.cursor()
doc_read_cursor = conn.cursor()
write_cursor = conn.cursor()

query = "select cikcode, accessionnumber,document_storage_url from filings_needing_table_extraction join html_doc_cache on (document_storage_url = url) where content_type = 'text/html'"
if args.stop_after is not None:
    query += f" limit {args.stop_after}"
read_cursor.execute(query)

if args.progress:
    import tqdm
    iterator = tqdm.tqdm(read_cursor, total=read_cursor.rowcount)
else:
    iterator = read_cursor

for row in iterator:
    cikcode = row[0]
    accessionnumber = row[1]
    document_url = row[2]
    # It might be faster to fetch the content in the read_cursor step, but
    # I'm vaguely worried about memory blowups. I suspect that we are going
    # to be bottlenecked on parsing the HTML anyway.
    doc_read_cursor.execute("select content, encoding from html_doc_cache where url = %s",
                            [document_url])
    doc_row = doc_read_cursor.fetchone()
    if doc_row is None:
        logging.error(f"Missing data for url = {document_url}")
    content = doc_row[0].tobytes().decode(doc_row[1])

    soup = BeautifulSoup(content, features="lxml")
    tables_found = False
    for i,t in enumerate(soup.find_all('table')):
        tables_found = True
        write_cursor.execute("insert into filing_tables (cikcode, accessionnumber, table_number, html) values (%s, %s, %s, %s)",
                             [cikcode, accessionnumber, i+1, str(t)])
    if not tables_found:
        write_cursor.execute("insert into filings_with_no_tables (cikcode, accessionnumber) values (%s, %s)", [cikcode, accessionnumber])
    conn.commit()
