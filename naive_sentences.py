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
parser.add_argument("--overlap",
                    default=0.25,
                    type=float,
                    help="How many sentences to overlap between nes_ranges")
parser.add_argument("--max-words-per-nes-range",
                    default=1000,
                    type=int,
                    help="GPT-3.5 has only 8k token memory for instance.")
args = parser.parse_args()

import pgconnect
import logging
import sys
import nltk
from bs4 import BeautifulSoup

if args.verbose:
    logging.basicConfig(
        format='%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s',
        level=logging.INFO,
        datefmt='%Y-%m-%d %H:%M:%S')
    logging.info("Starting")


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
if len(constraints) == 0:
    constraints = ""
else:
    constraints = " AND " + (' and '.join(constraints))

query = """
select filings.cikcode, filings.accessionnumber, content, encoding
from filings
join html_doc_cache on (url = document_storage_url)
left join naively_extracted_sentences using (cikcode, accessionnumber)
where naively_extracted_sentences.cikcode is null
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
    raw_content = row[2]
    encoding = row[3]

    logging.info(f"Processing {cikcode=}, {accession_number=}")
    if args.progress:
        iterator.set_description(f"{cikcode} {accession_number}")

    content = raw_content.tobytes().decode(encoding)
    soup = BeautifulSoup(content, features="lxml")

    execute_args = []
    sentence_lengths = []
    nes_range_start = 0
    saved_ranges = set()
    for i,sent in enumerate(nltk.sent_tokenize(soup.text)):
        sentence_length = len(nltk.word_tokenize(sent))
        write_cursor.execute("insert into naively_extracted_sentences (cikcode, accessionNumber, position_in_document, word_count, sentence_text) values (%s, %s, %s, %s, %s)",
                             [cikcode,
                              accession_number,
                              i,
                              sentence_length,
                              sent
                              ]
                             )
        sentence_lengths.append(sentence_length)
        total_tokens_so_far = sum(sentence_lengths[nes_range_start:])
        if total_tokens_so_far >= args.max_words_per_nes_range:
            nes_end_range = i - 1
            logging.info(f"Creating a range from sentences {nes_range_start} to {nes_end_range}")
            saved_ranges.update([(nes_range_start, nes_end_range)])
            
            write_cursor.execute("insert into nes_ranges (cikcode, accessionnumber, starting_sentence, ending_sentence) values (%s,%s,%s,%s)",
                                 [cikcode,
                                  accession_number,
                                  nes_range_start,
                                  nes_end_range])
            how_much_overlap = int((nes_end_range - nes_range_start) * args.overlap)
            logging.info(f"Calculated {how_much_overlap} for sentence overlap count (we are at sentence {i}).")
            new_nes_range_start = i - how_much_overlap
            logging.info(f"Which means the next range should start at {new_nes_range_start}")
            if new_nes_range_start == nes_range_start:
                # guarantee forward motion, even if inefficient
                new_nes_range_start = nes_range_start + 1
                logging.info(f"But since that would create a duplicate start point, we'll use {new_nes_range_start} instead")
            nes_range_start = new_nes_range_start
            logging.info(f"Will start range at {nes_range_start}")

    if (nes_range_start,i) not in saved_ranges:
        logging.info(f"Wrapping up the last range: {nes_range_start} to {i}")
        write_cursor.execute("insert into nes_ranges (cikcode, accessionnumber, starting_sentence, ending_sentence) values (%s,%s,%s,%s)",
                             [cikcode,
                              accession_number,
                              nes_range_start,
                              i])
    else:
        logging.info(f"Somehow, we already had the range {nes_range_start} to {i} saved")
    conn.commit()
