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
parser.add_argument("--nes-range-id",
                    type=int,
                    help="Only process this one NES range")
parser.add_argument("--prompt-id",
                    required=True,
                    help="Parse responses with this prompt_id")

args = parser.parse_args()

import pgconnect
import logging
import sys
import nltk
import os
import json

if args.verbose:
    logging.basicConfig(
        format='%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s',
        level=logging.INFO,
        datefmt='%Y-%m-%d %H:%M:%S')
    logging.info("Starting")


conn = pgconnect.connect(args.database_config)
read_cursor = conn.cursor()
sentence_cursor = conn.cursor()
write_cursor = conn.cursor()
prompt_cursor = conn.cursor()

constraints = []
constraint_args = [args.prompt_id]
if args.cikcode is not None:
    constraints.append("cikcode = %s")
    constraint_args.append(args.cikcode)
if args.accession_number is not None:
    constraints.append("accessionnumber = %s")
    constraint_args.append(args.accession_number)
if args.nes_range_id is not None:
    constraints.append("nes_range_id")
    constraint_args.append(args.nes_range_id)
if len(constraints) == 0:
    constraints = ""
else:
    constraints = " AND " + (' and '.join(constraints))

query = """
select nes_range_id, reply
from gpt_responses join nes_ranges using (nes_range_id)
left join experience_sentences using (nes_range_id, prompt_id)
left join unparseable_gpt_responses using (nes_range_id, prompt_id)
left join content_free_gpt_responses using (nes_range_id, prompt_id)
where experience_sentences.sentence is null
  and unparseable_gpt_responses.when_failed is null
  and content_free_gpt_responses.when_checked is null
  and prompt_id = %s
""" + constraints + " order by cikcode, accessionnumber"

if args.stop_after is not None:
    query += f" limit {args.stop_after}"

read_cursor.execute(query, constraint_args)

if args.progress:
    import tqdm
    iterator = tqdm.tqdm(read_cursor, total=read_cursor.rowcount)
else:
    iterator = read_cursor

for row in iterator:
    nes_range_id = row[0]
    reply = row[1]
    logging.info(f"Processing {nes_range_id=}")
    if args.progress:
        iterator.set_description(f"{nes_range_id}")
    try:
        answer = json.loads(reply)
        logging.info("Reply was in good JSON format")
        wrote_something = False
        for obj in answer:
            logging.info("Processing object")
            if 'director_id' in obj:
                director_id = obj['director_id']
                logging.info(f"Director is defined: {director_id}")
                sentences = obj.get('relevant_sentences', [])
                logging.info(f"{len(sentences)=}")
                if type(sentences) != type([]):
                    sentences = [sentences]
                for sentence in sentences:
                    logging.info(f"Writing sentence for {director_id=}:  {sentence}")
                    write_cursor.execute("insert into experience_sentences (director_id, sentence, nes_range_id, prompt_id) values (%s, %s, %s, %s)",
                                         [director_id,
                                          sentence,
                                          nes_range_id,
                                          args.prompt_id])
                    wrote_something = True
        if not wrote_something:
            logging.info("While it was valid JSON, there was no information we want to preserve")
            write_cursor.execute("insert into content_free_gpt_responses (nes_range_id, prompt_id) values (%s, %s)",
                                         [nes_range_id, args.prompt_id])
    except json.JSONDecodeError:
        logging.info("Didn't understand this JSON" + reply)
        write_cursor.execute("insert into unparseable_gpt_responses (nes_range_id, prompt_id) values (%s, %s)",
                             [nes_range_id, args.prompt_id])
    conn.commit()
