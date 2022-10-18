#!/usr/bin/env python3

import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--database-config",
                    default="db.conf",
                    help="Parameters to connect to the database")
parser.add_argument("--name")
parser.add_argument("--sector")
parser.add_argument("--ticker")
parser.add_argument("--json", action="store_true", help="Output to JSON instead of a table")
args = parser.parse_args()

import pgconnect
import sys
import pandas
import json
conn = pgconnect.connect(args.database_config)
read_cursor = conn.cursor()

query = "select cikcode, sector, ticker, board_name from listed_company_details"
constraints = []
query_args = []

if args.name is not None:
    constraints.append("board_name ilike %s")
    query_args.append("%" + args.name + "%")
if args.sector is not None:
    constraints.append("sector ilike %s")
    query_args.append("%" + args.sector + "%")
if args.ticker is not None:
    constraints.append("ticker ilike %s")
    query_args.append(args.ticker)

if len(constraints) > 0:
    query += " WHERE " + (" and ".join(constraints))

read_cursor.execute(query, query_args)
if read_cursor.rowcount == 0:
    sys.exit("No matching listed companies")
records = [{'cikcode': row[0], 'Name': row[3], 'Ticker': row[2], 'Sector': row[1]} for row in read_cursor]

if args.json:
    print(json.dumps(records, indent=2))
else:
    companies = pandas.DataFrame.from_records(records)
    print(companies)
