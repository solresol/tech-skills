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
parser.add_argument("--form",
                    default="DEF 14A",
                    help="Which forms to select for download")

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
named_entity_cursor = conn.cursor()
director_cursor = conn.cursor()
pronoun_cursor = conn.cursor()

constraints = []
constraint_args = [args.form]
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
left join pronoun_resolved_filings using (cikcode, accessionNumber)
where when_resolved is null
  and form = %s
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
    write_cursor.execute("insert into pronoun_resolved_filings (cikcode, accessionNumber) values (%s, %s) returning pronoun_resolved_filing_id", [cikcode, accession_number])
    prf_row = write_cursor.fetchone()
    resolution_id = prf_row[0]

    director_cursor.execute("select director_id, surname from directors_active_on_filing_date where cikcode = %s and accessionnumber = %s",
                            [cikcode, accession_number])
    director_information = { x[1] : x[0] for x in director_cursor }

    inner_cursor.execute("select sentence_id, document_position, sentence_number_within_fragment from sentences  where cikcode = %s and accessionNumber = %s order by document_position, sentence_number_within_fragment",
                         [cikcode, accession_number])
    last_named_entity = None
    named_entity_sentence = None
    named_entity_label = None
    last_document_position = None

    for sentence_id, document_position, sentence_number_within_fragment in inner_cursor:
        if last_document_position is None or document_position > last_document_position + 1:
            # We've passed over a heading, or the beginning of the document. Either way,
            # the last named entity is obsolete.
            last_named_entity = None
            named_entity_sentence = None
            named_entity_label = None
            last_document_position = document_position
        named_entity_cursor.execute("""
             select director_id, named_entity
               from named_entities
               join directors_active_on_filing_date_materialized on (named_entity ilike '%%' || surname || '%%')
             where sentence_id = %s
               and label = 'PERSON'
               and cikcode = %s
               and accessionNumber = %s
            """, [sentence_id, cikcode, accession_number])
        first_person = named_entity_cursor.fetchone()
        if first_person is not None:
            second_person = named_entity_cursor.fetchone()
            if second_person is not None:
                # Several directors in the same sentence. Really can't guess what's going on.
                last_named_entity = None
                named_entity_sentence = None
                named_entity_label = None
            else:
                # Just one director mentioned
                director_id = first_person[0]
                last_named_entity = first_person[1]
                named_entity_sentence = sentence_id
                named_entity_label = 'PERSON'
                logging.info(f"{document_position}.{sentence_number_within_fragment} mentions {last_named_entity} ({director_id=})")
        if last_named_entity is not None:
            pronoun_cursor.execute("select pronoun, tag from pronouns where sentence_id = %s",
                                   [sentence_id])
            for pronoun, tag in pronoun_cursor:
                write_cursor.execute("insert into director_pronoun_resolution (pronoun_sentence_id, pronoun, tag, named_entity_sentence_id, named_entity, label, filing_resolution_id, director_id) values (%s, %s,%s,%s,%s,%s,%s, %s)",
                                     [sentence_id, pronoun, tag, named_entity_sentence, last_named_entity, named_entity_label, resolution_id, director_id])
    conn.commit()

logging.info("Completed")
