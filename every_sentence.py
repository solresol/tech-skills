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
args = parser.parse_args()

import pgconnect
import logging
import pandas
import functools
import sys
import director_name_handling
import spacy
import re

if args.verbose:
    logging.basicConfig(
        format='%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s',
        level=logging.INFO,
        datefmt='%Y-%m-%d %H:%M:%S')
    logging.info("Starting")


logging.info("Loading spacy")
nlp = spacy.load('en_core_web_sm')

conn = pgconnect.connect(args.database_config)
read_cursor = conn.cursor()
sentence_read_cursor = conn.cursor()
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
select cikcode, accessionnumber, document_position, position_of_leader, plaintext
from document_text_positions
left join sentences using (cikcode, accessionnumber, document_position)
where sentences.sentence_id is null
""" + constraints + " order by cikcode, accessionnumber, document_position"

if args.stop_after is not None:
    query += f" limit {args.stop_after}"
    
read_cursor.execute(query, constraint_args)

if args.progress:
    import tqdm
    iterator = tqdm.tqdm(read_cursor, total=read_cursor.rowcount)
else:
    iterator = read_cursor


@functools.lru_cache(10)
def get_director_details(accession_number, cikcode):
    sentence_read_cursor.execute("select director_id, surname from directors_active_on_filing_date where accessionnumber = %s and cikcode = %s",
                                 [accession_number, cikcode])
    answer = {}
    for row in sentence_read_cursor:
        key = director_name_handling.remove_name_suffixes(row[1])
        val = row[0]
        answer[key] = val
    return answer

@functools.lru_cache(10)
def most_recent_director_mention(accession_number, cikcode, document_position):
    sentence_read_cursor.execute("""select position_of_leader 
        from document_text_positions
       where accession_number = %s and cikcode = %s and document_position = %s""",
                                 [accession_number, cikcode, document_position])
    row = sentence_read_cursor.fetchone()
    if row is None:
        return None
    position_of_leader = row[0]
    sentence_read_cursor.execute("""
select sentence_id, director_id, rank() over (order by sentence_number_within_document desc) as recency
      from sentences join document_text_positions using (cikcode, accessionnumber, document_position)
      where has_single_director_mention
        and accession_number = %s
        and cikcode = %s
        and document_position > %s 
        and document_position < %s order by 3 limit 1""",
                                 [accession_number, cikcode, position_of_leader, document_position])
    row = sentence_read_cursor.fetchon()
    if row is None:
        return None
    return (row[0], row[1])

for row in iterator:
    cikcode = row[0]
    accession_number = row[1]
    document_position = row[2]
    logging.info(f"Processing {cikcode=}, {accession_number=}, {document_position=}")
    if args.progress:
        iterator.set_description(f"{cikcode} {accession_number} {document_position}")
    position_of_leader = row[3]
    plaintext = row[4]
    director_names = get_director_details(accession_number, cikcode)
    doc = nlp(plaintext)
    for sent in doc.sents:
        sentence_as_data = sent.to_bytes()
        print(sent)
    
