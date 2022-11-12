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
from bs4 import BeautifulSoup
import re
font_size = re.compile('font-size:(\d+)')

if args.verbose:
    logging.basicConfig(
        format='%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s',
        level=logging.INFO,
        datefmt='%Y-%m-%d %H:%M:%S')
    logging.info("Starting")

conn = pgconnect.connect(args.database_config)
read_cursor = conn.cursor()
html_read_cursor = conn.cursor()
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
select cikcode, accessionnumber, filingdate, document_storage_url, 
  filings_with_textual_parse_errors.cikcode as failed_parse,
  filings_parsed_successfully.cikcode as succeeded_parse
from filings
left join filings_with_textual_parse_errors using (cikcode, accessionnumber)
left join filings_parsed_successfully  using (cikcode, accessionnumber)
where filings_with_textual_parse_errors.cikcode is null
  and filings_parsed_successfully.cikcode is null
  and form = 'DEF 14A'
""" + constraints

if not args.random_order:
    query += " order by cikcode, accessionnumber"
if args.stop_after is not None:
    query += f" limit {args.stop_after}"

read_cursor.execute(query, constraint_args)

if args.progress:
    import tqdm
    iterator = tqdm.tqdm(read_cursor, total=read_cursor.rowcount)
else:
    iterator = read_cursor


def headings_tables_and_text(congee, level_leader_position=None):
    global last_table_number_seen
    global last_heading_number_seen
    global position
    global text_blobs
    
    current_text_blob = ""
    for child in congee.children:
        if child.name in ['script', 'img', 'title', 'noscript', 's', 'del']:
            continue
        if child.name is None:
            # then it's a navigable string
            if child.text.strip() == '':
                continue
            # so now it's a navigable string that says something
            #print(f"An ordinary blob of text at {position=}, with {level_leader_position=}: {child.text}")
            current_text_blob += child.text + ' '
            continue
        if child.name == 'table':
            if current_text_blob.strip() != '':
                position += 1
                if level_leader_position is None:
                    level_leader_position = position
                text_blobs.append(("TEXT",position, level_leader_position, current_text_blob.strip()))
                current_text_blob = ''

            last_table_number_seen += 1
            position += 1
            text_blobs.append(("TABLE", position, last_table_number_seen))
            #print(indent, f"Then we saw table {last_table_number_seen} at position {position}")
            # It is possible that there are sentences inside tables that might be informative. Not sure.
            headings_tables_and_text(child, level_leader_position=None)
            continue
        if child.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            if current_text_blob.strip() != '':
                position += 1
                if level_leader_position is None:
                    level_leader_position = position
                text_blobs.append(("TEXT", position, level_leader_position, current_text_blob.strip()))
                current_text_blob = ''
            position += 1
            text_blobs.append(("HEADING", child.name, position, child.text))
            level_leader_position = position
            continue
        if child.name in ['hr', 'br']:
            if current_text_blob.strip() != '':
                position += 1
                if level_leader_position is None:
                    level_leader_position = position                
                text_blobs.append(("TEXT", position, level_leader_position, current_text_blob.strip()))
                current_text_blob = ''
            level_leader_position = None
            continue
        if child.find('table'):
            if current_text_blob.strip() != '':
                position += 1
                if level_leader_position is None:
                    level_leader_position = position
                text_blobs.append(("TEXT", position, level_leader_position, current_text_blob.strip()))
                current_text_blob = ''
            #print(indent,"Has child table. Burrowing down")
            headings_tables_and_text(child, level_leader_position=level_leader_position)
            continue
        if child.find('p'):
            if current_text_blob.strip() != '':
                position += 1
                if level_leader_position is None:
                    level_leader_position = position
                text_blobs.append(("TEXT", position, level_leader_position, current_text_blob.strip()))
                current_text_blob = ''
            #print(indent, "Has a paragraph child. Burrowing down", child.text)
            headings_tables_and_text(child, level_leader_position=level_leader_position)
            continue
        # We are not a table. We are not a navigable string. We are not a heading.
        # There are no paragraphs below us. There are no tables below us.
        if child.name in ['tr', 'td', 'p', 'li', 'ul', 'ol', 'dd', 'dt', 'div', 'caption', 'main',
                          'blockquote', 'datalist', 'details', 'page', 'dl', 'html', 'th']:
            # These don't break the flow. We can keep level leader, but we do need to clear the context
            # before handling them.
            if current_text_blob.strip() != '':
                position += 1
                if level_leader_position is None:
                    level_leader_position = position
                text_blobs.append(("TEXT", position, level_leader_position, current_text_blob.strip()))
                current_text_blob = ''
            headings_tables_and_text(child, level_leader_position=level_leader_position)
            continue 
        if child.name in ['b', 'i', 'em', 'a', 'u', 'center', 'sup', 'strong']:
            #print(f"An ordinary blob of text at {position=}, with {level_leader_position=}: {child.text}")
            current_text_blob += child.text + ' '
            continue 
        if child.name == 'font':
            size_increase = False
            if 'size' in child.attrs:
                if child.attrs['size'].startswith('+'):
                    size_increase = True
                elif child.attrs['size'] in ['4', '5', '6', '7']:
                    size_increase = True
                    # Not completely true. It depends on how big we were before.
                    # But it *probably* means a bigger font
                continue
            if 'style' in child.attrs:
                font_size_match = font_size.search(child.attrs['style'])
                if font_size_match:
                    if float(font_size_match.group(1)) > 12:
                        size_increase = True
                continue
            if size_increase:
                # It's like a heading.
                if current_text_blob.strip() != '':
                    position += 1
                    if level_leader_position is None:
                        level_leader_position = position
                    text_blobs.append(("TEXT", position, level_leader_position, current_text_blob.strip()))
                    current_text_blob = ''
                position += 1
                text_blobs.append(("HEADING", "H0", position, child.text))
                level_leader_position = position
                continue
            # Not a size increase. Probably harmless colour change or something.
            current_text_blob += child.text + ' '
            continue
        # No idea what to do. Panic.
        global write_cursor
        global conn
        global cikcode
        global accession_number
        error_message = f"Don't know how to handle {child.name} tag in {child}"
        write_cursor.execute("insert into filings_with_textual_parse_errors (cikcode, accessionNumber, errors) values (%s, %s, %s)",
                             [cikcode, accession_number,error_message])
                              
        conn.commit()
        logging.critical(error_message)
        sys.exit(1)
    if current_text_blob.strip() != '':
        position += 1
        if level_leader_position is None:
            level_leader_position = position
        text_blobs.append(("TEXT", position, level_leader_position, current_text_blob))
        current_text_blob = ''

for row in iterator:
    cikcode = row[0]
    accession_number = row[1]
    logging.info(f"Processing {cikcode=}, {accession_number=}")
    if args.progress:
        iterator.set_description(cikcode + " " + accession_number)
    filingdate = row[2]
    document_storage_url = row[3]
    logging.info(f"{document_storage_url=}") 
    html_read_cursor.execute("select content from html_doc_cache where url = %s", [document_storage_url])
    html_row = html_read_cursor.fetchone()
    if html_row is None:
        # It's bad, but we can recover
        write_cursor.execute("insert into filings_with_textual_parse_errors (cikcode, accessionNumber, errors) values (%s, %s, %s)",
                             [cikcode, accession_number,
                              f"HTML content is missing from the html_doc_cache table"])
        conn.commit()
        continue
    html = html_row[0]
    logging.info("HTML fetched")
    soup = BeautifulSoup(html.tobytes(), features='lxml')
    logging.info("HTML parsed")
    last_table_number_seen=0
    last_heading_number_seen=0
    position=0
    text_blobs = []
    headings_tables_and_text(soup)
    logging.info("Text-level parsing complete")
    for t in text_blobs:
        if t[0] == 'TEXT':
            write_cursor.execute("insert into document_text_positions (cikcode, accessionNumber, document_position, position_of_leader, plaintext) values (%s, %s, %s, %s,%s)",
                                 [cikcode, accession_number, t[1], t[2], t[3]])
        if t[0] == 'HEADING':
            write_cursor.execute("insert into document_headings (cikcode, accessionNumber, heading_level, heading_text, document_position) values (%s, %s, %s, %s, %s)",
                                 [cikcode, accession_number, t[1][1], t[3], t[2]])
        if t[0] == 'TABLE':
            write_cursor.execute("insert into document_table_positions (cikcode, accessionNumber, table_number, document_position) values (%s, %s, %s, %s)",
                                 [cikcode, accession_number, t[2], t[1]])
    write_cursor.execute("insert into filings_parsed_successfully (cikcode, accessionNumber) values (%s, %s)",
                         [cikcode, accession_number])
    logging.info("Committing transaction")
    conn.commit()
