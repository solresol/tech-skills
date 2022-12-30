#!/usr/bin/env python3

# A silly little program which is handy to use in conjunction with xargs

import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--database-config",
                    default="db.conf",
                    help="Parameters to connect to the database")
args = parser.parse_args()

import pgconnect
import sys
import pandas
import json
conn = pgconnect.connect(args.database_config)
read_cursor = conn.cursor()

query = "select distinct(cikcode) from listed_company_details"

read_cursor.execute(query)
for row in read_cursor:
    print(row[0])
