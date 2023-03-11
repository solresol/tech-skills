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
parser.add_argument("--starting-sentence",
                    type=int,
                    help="Only process the NES range starting with this sentence number (needs cikcode and acession number to make sense")
parser.add_argument("--prompt-id",
                    required=True,
                    help="Use this prompt_id (probably from create_prompt.py)")
parser.add_argument("--openai-key-file",
                    default="~/.openai.key")
parser.add_argument("--show-prompt", action="store_true", help="Display the prompts that are sent to OpenAI")
parser.add_argument("--show-response", action="store_true", help="Display the response returned by OpenAI")
parser.add_argument("--dry-run", action="store_true", help="Don't send anything to OpenAI")

args = parser.parse_args()

import pgconnect
import logging
import sys
import nltk
from bs4 import BeautifulSoup
import os
import openai


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

read_cursor.execute("select model, prompt_prefix, prompt_postfix from prompts where prompt_id = %s",
                    [args.prompt_id])
row = read_cursor.fetchone()
if row is None:
    sys.exit(f"Prompt ID = {args.prompt_id} not found")
model = row[0]
prompt_prefix = row[1]
prompt_postfix = row[2]
logging.info("Prompt fetched")

openai.api_key = open(os.path.expanduser(args.openai_key_file)).read().strip()

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
if args.starting_sentence is not None:
    constraints.append("starting_sentence")
    constraint_args.append(argsg.starting_sentence)
if len(constraints) == 0:
    constraints = ""
else:
    constraints = " AND " + (' and '.join(constraints))

query = """
with existing_responses as (select nes_range_id from gpt_responses where prompt_id = %s)
select cikcode, accessionNumber, starting_sentence, ending_sentence, nes_range_id
from nes_ranges
left join existing_responses using (nes_range_id)
left join nes_ranges_skipped using (nes_range_id)
where existing_responses is null
  and nes_ranges_skipped.when_skipped is null
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
    cikcode = row[0]
    accession_number = row[1]
    starting_sentence = row[2]
    ending_sentence = row[3]
    nes_range_id = row[4]

    logging.info(f"Processing {cikcode=}, {accession_number=} {nes_range_id=}")
    if args.progress:
        iterator.set_description(f"{cikcode} {accession_number} {starting_sentence}")


    sentence_cursor.execute("select count(*) from naively_extracted_sentences, vocabulary_required_for_prompt where position_in_document between %s and %s and cikcode = %s and accessionNumber = %s and sentence_text ilike ('%%' || vocab_item || '%%') and prompt_id = %s",
                            [starting_sentence,
                             ending_sentence,
                             cikcode,
                             accession_number,
                             args.prompt_id])
    count_row = sentence_cursor.fetchone()
    count = count_row[0]

    if count == 0:
        logging.info("No vocabulary items were present, so this can't possibly be relevant to our project")
        write_cursor.execute("insert into nes_ranges_skipped (nes_range_id) values (%s)",
                             [nes_range_id])
        conn.commit()
        continue

    sentence_cursor.execute("select sentence_text from naively_extracted_sentences where position_in_document between %s and %s and cikcode = %s and accessionNumber = %s",
                            [starting_sentence,
                             ending_sentence,
                             cikcode,
                             accession_number])
    text = "\n".join([x[0] for x in sentence_cursor])
    prompt = prompt_prefix + text + prompt_postfix
    logging.info("Querying OpenAI")
    if args.show_prompt:
        print("PROMPT>>", prompt)
    if args.dry_run:
        continue
    response = openai.ChatCompletion.create(
      model=model,
      messages=[
          {"role": "user", "content": prompt }
      ]
    )
    reply_text = response['choices'][0]['message']['content']
    logging.info("Received content")
    
    write_cursor.execute("insert into gpt_responses (nes_range_id, prompt_id, reply) values (%s, %s, %s)",
                             [nes_range_id,
                              args.prompt_id,
                              reply_text
                              ]
                         )
    if args.show_response:
        print("REPLY>>",reply_text)
    conn.commit()
