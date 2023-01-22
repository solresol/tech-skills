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
                    help="Don't try to process every table. Stop after this number")
parser.add_argument("--cikcode",
                    type=int,
                    help="Only process documents from this cikcode")
parser.add_argument("--accession-number",
                    help="Only process documents with this accession number")
parser.add_argument("--random-order",
                    action="store_true",
                    help="It doesn't matter what order things get processed in. Save the time doing the sort")

args = parser.parse_args()

import pgconnect
import logging
import pandas
import functools
import sys
import director_name_handling
import spacy
import re
import collections

if args.verbose:
    logging.basicConfig(
        format='%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s',
        level=logging.INFO,
        datefmt='%Y-%m-%d %H:%M:%S')
    logging.info("Starting")


conn = pgconnect.connect(args.database_config)
read_cursor = conn.cursor()
inner_cursor = conn.cursor()
write_cursor = conn.cursor()

constraints = []
constraint_args = []
if args.cikcode is not None:
    constraints.append("cikcode = %s")
    constraint_args.append(args.cikcode)
if args.accession_number is not None:
    constraints.append("accessionnumber = %s")
    constraint_args.append(args.accession_number)
if len(constraints) == 0:
    constraints = ""
else:
    constraints = " AND " + (' and '.join(constraints))

query = """
select
       cikcode, accessionnumber
from filings
left join sentence_numbered_filings using (cikcode, accessionNumber)
where sentence_numbered_filings.when_parsed is null
  and form = 'DEF 14A'
""" + constraints


if not args.random_order:
    query += " order by  cikcode, accessionNumber "

if args.stop_after is not None:
    query += f" limit {args.stop_after}"


logging.info("Preparing query")
read_cursor.execute(query, constraint_args)

if args.progress:
    import tqdm
    iterator = tqdm.tqdm(read_cursor, total=read_cursor.rowcount)
else:
    iterator = read_cursor

logging.info("Starting")
for row in iterator:
    cikcode = row[0]
    accession_number = row[1]
    logging.info(f"Processing {cikcode=} {accession_number=}")
    inner_cursor.execute("select sentence_id, document_position, sentence_number_within_fragment from sentences  where cikcode = %s and accessionNumber = %s order by document_position, sentence_number_within_fragment",
                         [cikcode, accession_number])
    sentence_number = 1
    for sentence_id, document_position, sentence_number_within_fragment in inner_cursor:
        write_cursor.execute("insert into sentences_within_document (sentence_id, sentence_number_within_document) values (%s, %s)", [sentence_id, sentence_number])
        sentence_number += 1
    write_cursor.execute("insert into sentence_numbered_filings (cikcode, accessionNumber, number_of_sentences) values (%s, %s, %s)", [cikcode, accession_number, sentence_number])
    conn.commit()

logging.info("Completed")
