#!/usr/bin/env python3

import argparse
import datetime

parser = argparse.ArgumentParser()
parser.add_argument("--database-config",
                    default="db.conf",
                    help="Parameters to connect to the database")
parser.add_argument("--year",
                    default=datetime.datetime.now().year - 1,
                    type=int,
                    help="Which year's filings to download (defaults to last year)")
parser.add_argument("--progress",
                    action="store_true",
                    help="Show a progress bar")
parser.add_argument("--form",
                    default="DEF 14A",
                    help="Which forms to select for download")
parser.add_argument("--retry-past-failures",
                    action="store_true",
                    help="If a document was unfetchable in the past, normally we don't try again, but with this option we will")
args = parser.parse_args()

import pgconnect
import requests
import logging
import time

conn = pgconnect.connect(args.database_config)
read_cursor = conn.cursor()
write_cursor = conn.cursor()

unfetched = """
  select document_storage_url
    from filings
   where form = %s
     and extract(year from filingDate) = %s
     and document_storage_url not in (select url from html_doc_cache)
"""

if args.retry_past_failures:
    pass
else:
    unfetched += " and document_storage_url not in (select url from html_fetch_failures)"

read_cursor.execute(unfetched, [args.form, args.year])

if args.progress:
    import tqdm
    iterator = tqdm.tqdm(read_cursor, total=read_cursor.rowcount)
else:
    iterator = read_cursor

for row in iterator:
    url = row[0]
    my_user_agent = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.0.0 Safari/537.36'
    r = requests.get(url, headers={'User-Agent': my_user_agent})
    if r.status_code != 200:
        write_cursor.execute("insert into html_fetch_failures (url, status_code) values (%s, %s) on conflict (url) do update set status_code = %s, date_attempted = current_timestamp",
                             [url, r.status_code, r.status_code])
        logging.error(f"Could not fetch {url}: {r.status_code}")
        conn.commit()
        continue
    write_cursor.execute("insert into html_doc_cache (url, content, encoding, content_type) values (%s, %s, %s, %s)", [url, r.content, r.encoding, r.headers.get('content-type')])
    conn.commit()
    # Chill out so we don't hit rate limits
    time.sleep(1)
