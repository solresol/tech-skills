#!/usr/bin/env python

import argparse
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--database-config",
                    default="db.conf",
                    help="Parameters to connect to the database")
parser.add_argument("--prefix-file",
                    required=True,
                    help="Filename to read the prompt prefix from")
# To-do:
#  - let the user specify the prompt-postfix
#  - let the user specify a model
#  - edit an existing prompt (???)
#  - search to see if a prompt is already there.
args = parser.parse_args()

import pgconnect
conn = pgconnect.connect(args.database_config)
write_cursor = conn.cursor()

prefix_contents = open(args.prefix_file).read()

query = "insert into prompts (prompt_prefix) values (%s) returning prompt_id"
write_cursor.execute(query, [prefix_contents])

row = write_cursor.fetchone()
if row is None:
    sys.exit("No prompt id was returned")

prompt_id = row[0]
print(prompt_id)

