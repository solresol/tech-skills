#!/usr/bin/env python

import argparse
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--database-config",
                    default="db.conf",
                    help="Parameters to connect to the database")
parser.add_argument("--new",
                    action="store_true",
                    help="Create a new prompt")
parser.add_argument("--prompt-id",
                    required=True,
                    help="A unique string for this prompt")
parser.add_argument("--text",
                    help="Filename to read some text from for the next part of the prompt")
parser.add_argument("--company-name",
                    action="store_true",
                    help="The next step in the prompt creation process should be to add the company name")
parser.add_argument("--list-directors",
                    action="store_true",
                    help="The next step in the prompt creation process should be to list the company directors")
parser.add_argument("--document",
                    action="store_true",
                    help="The next step int he prompt creation process is to insert the def 14a form (or other document)")
# To-do:
#  - let the user specify a model
#  - edit an existing prompt (???)
#  - do we need sanity checks that we aren't inserting the document twice?

args = parser.parse_args()


import pgconnect
conn = pgconnect.connect(args.database_config)
write_cursor = conn.cursor()
read_cursor = conn.cursor()

params = []
param_values = []

if args.new:
    write_cursor.execute("insert into prompts (prompt_id) values (%s) returning prompt_id",
                         [args.prompt_id])

read_cursor.execute("select coalesce(max(section_number), 0) from prompt_sections where prompt_id = %s",
                    [args.prompt_id])
row = read_cursor.fetchone()
largest = row[0]
next_section = largest+1

if args.text is not None:
    if args.company_name:
        sys.exit("--text cannot also be specified with --company-name")
    if args.list_directors:
        sys.exit("--text cannot also be specified with --list-directors")
    if args.document:
        sys.exit("--text cannot also be specified with --document")
    contents = open(args.text).read()
    write_cursor.execute("insert into prompt_sections (prompt_id, section_number, insert_raw_text, raw_text) values (%s, %s, true, %s)",
                         [args.prompt_id, next_section, contents])

if args.company_name:
    if args.list_directors:
        sys.exit("--company-name cannot also be specified with --list-directors")
    if args.document:
        sys.exit("--company-name cannot also be specified with --document")
    write_cursor.execute("insert into prompt_sections (prompt_id, section_number, insert_company_name) values (%s, %s, true)",
                         [args.prompt_id, next_section])

if args.list_directors:
    if args.document:
        sys.exit("--list-directors cannot also be specified with --document")
    write_cursor.execute("insert into prompt_sections (prompt_id, section_number, insert_directors) values (%s, %s, true)",
                         [args.prompt_id, next_section])

if args.document:
    write_cursor.execute("insert into prompt_sections (prompt_id, section_number, insert_document) values (%s, %s, true)",
                         [args.prompt_id, next_section])
conn.commit()
