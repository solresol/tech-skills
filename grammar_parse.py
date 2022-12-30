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
parser.add_argument("--document_position",
                    help="Only process this document position (somewhat silly unless cikcode and accession number are also specified")
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


logging.info("Loading spacy")
nlp = spacy.load('en_core_web_sm')

conn = pgconnect.connect(args.database_config)
read_cursor = conn.cursor()
write_cursor = conn.cursor()

constraints = []
constraint_args = []
if args.cikcode is not None:
    constraints.append("cikcode = %s")
    constraint_args.append(args.cikcode)
if args.accession_number is not None:
    constraints.append("accessionnumber = %s")
    constraint_args.append(args.accession_number)
if args.document_position is not None:
    constraints.append("document_position = %s")
    constraint_args.append(args.document_position)    
if len(constraints) == 0:
    constraints = ""
else:
    constraints = " AND " + (' and '.join(constraints))

query = """
select cikcode, accessionnumber, document_position, plaintext
from document_text_positions
left join spacy_parses using (cikcode, accessionnumber, document_position)
where spacy_parses.spacy_blob is null
""" + constraints

if not(args.random_order):
    query += " order by cikcode, accessionnumber, document_position"
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
    document_position = row[2]
    logging.info(f"Processing {cikcode=}, {accession_number=}, {document_position=}")
    if args.progress:
        iterator.set_description(f"{cikcode} {accession_number} {document_position}")
    plaintext = row[3]
    doc = nlp(plaintext)
    write_cursor.execute("insert into spacy_parses (cikcode, accessionNumber, document_position, spacy_blob) values (%s, %s, %s, %s)",
                         [cikcode, accession_number, document_position, doc.to_bytes()])
    for (i,sent) in enumerate(doc.sents):
        write_cursor.execute("insert into sentences (cikcode, accessionNumber, document_position, sentence_number_within_fragment, sentence_text) values (%s, %s, %s, %s, %s) returning sentence_id",
                             [cikcode, accession_number, document_position, i+1, str(sent)])
        srow = write_cursor.fetchone()
        sentence_id = srow[0]
        seen_ents = set()
        for ent in sent.ents:
            if str((ent,ent.label_)) not in seen_ents:
                write_cursor.execute("insert into named_entities (sentence_id, named_entity, label) values (%s,%s, %s)",
                                     [sentence_id, str(ent), ent.label_])
                seen_ents.update([str((ent,ent.label_))])
        noun_chunks = collections.defaultdict(int)
        for chunk in sent.noun_chunks:
            noun_chunks[str(chunk)] += 1
        for noun_chunk, ncount in noun_chunks.items():
            write_cursor.execute("insert into noun_chunks (sentence_id, noun_chunk, repeat_count) values (%s, %s, %s)", [sentence_id, str(noun_chunk), ncount])
        prepositions = collections.defaultdict(int)
        for word in sent:
            if word.tag_.startswith('PRP'):
                prepositions[(str(word), word.tag_)] += 1
        for prep, count in prepositions.items():
            write_cursor.execute("insert into prepositions (sentence_id, preposition, tag, repeat_count) values (%s, %s, %s, %s)",
                                 [sentence_id, prep[0], prep[1], count])
    conn.commit()
    
logging.info("Completed")
