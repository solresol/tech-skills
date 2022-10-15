#!/usr/bin/env python3

import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--database-config",
                    default="db.conf",
                    help="Parameters to connect to the database")
parser.add_argument("--accessionnumber")
parser.add_argument("--cikcode")
parser.add_argument("--url")
args = parser.parse_args()

import pgconnect
import sys
conn = pgconnect.connect(args.database_config)
read_cursor = conn.cursor()

if args.url is None and args.accessionnumber is None:
    sys.exit("Must specify at one of accessionnumber and url")

if args.url is not None and args.accessionnumber is not None:
    sys.exit("Must specify at only one of accessionnumber and url")

if args.url is None:
    if args.cikcode is None:
        read_cursor.execute("select document_storage_url from filings where accessionnumber = %s", [args.accessionnumber])
        if read_cursor.rowcount > 1:
            sys.exit("There are multiple filings with that accession number")
        row = read_cursor.fetchone()
        if row is None:
            sys.exit("There is no filing with that accession number")
        url = row[0]
    if args.cikcode is not None:
        read_cursor.execute("select document_storage_url from filings where accessionnumber = %s and cikcode = %s", [args.accessionnumber, args.cikcode])
        row = read_cursor.fetchone()
        if row is None:
            sys.exit("There is no filing with that accession number and cikcode")
        url = row[0]
if args.url is not None:
    url = args.url

read_cursor.execute("select content, encoding from html_doc_cache where url = %s", [url])
row = read_cursor.fetchone()
if row is None:
    sys.exit("URL has not been fetched")
bytes = row[0].tobytes()
print(bytes.decode(row[1]))
#print(type(bytes))
#print(dir(bytes))
