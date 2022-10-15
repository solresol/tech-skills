#!/usr/bin/env python3

import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--database-config",
                    default="db.conf",
                    help="Parameters to connect to the database")
parser.add_argument("--table-id")
parser.add_argument("--cikcode")
parser.add_argument("--accession-number")
parser.add_argument("--table-number")
parser.add_argument("--csv", action='store_true', help="Output CSV file")
parser.add_argument("--html", action='store_true', help="Output HTML")
args = parser.parse_args()

import pgconnect
import sys
conn = pgconnect.connect(args.database_config)
read_cursor = conn.cursor()

if args.table_id is None:
    if args.cikcode is None or args.accession_number is None or args.table_number is None:
        sys.exit("Must supply either --table-id or else all of --cikcode, --accession-number and --table-number")
    read_cursor.execute("select html from filing_tables where cikcode = %s and accession_number = %s and table_number = %s", [args.cikcode, args.accession_number, args.table_number])
if args.table_id is not None:
    if args.cikcode is not None or args.accession_number is not None or args.table_number is not None:
        sys.exit("If --table-id is given, there is no need to supply --cikcode, --accession-number or --table-number")
    read_cursor.execute("select html from filing_tables where table_id = %s", [args.table_id])

row = read_cursor.fetchone()
if row is None:
    sys.exit("No such table")

content = row[0]
if args.html:
    # Maybe pretty print it somehow?
    print(content)

if args.csv:
    import pandas
    tables = pandas.read_html(content)
    the_table = tables[0]
    the_table.to_csv(sys.stdout, index=False)
