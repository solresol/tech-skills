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
                    help="Only process tables from this cikcode")
parser.add_argument("--accession-number",
                    type=int,
                    help="Only process tables from this accession number")
parser.add_argument("--table-id",
                    type=int,
                    help="Only process the table number specified")
parser.add_argument("--random-order",
                    action="store_true",
                    help="It doesn't matter what order things get processed in. Save the time doing the sort")
args = parser.parse_args()

import pgconnect
import logging
import pandas
import functools
import sys
from html_table_extractor.extractor import Extractor
import director_name_handling

if args.verbose:
    logging.basicConfig(
        format='%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s',
        level=logging.INFO,
        datefmt='%Y-%m-%d %H:%M:%S')
    logging.info("Starting")

conn = pgconnect.connect(args.database_config)
read_cursor = conn.cursor()
director_read_cursor = conn.cursor()
write_cursor = conn.cursor()

constraints = []
constraint_args = []
if args.cikcode is not None:
    constraints.append("cikcode = %s")
    constraint_args.append(args.cikcode)
if args.accession_number is not None:
    constraints.append("accessionnumber = %s")
    constraint_args.append(args.accession_number)
if args.table_id is not None:
    constraints.append("filing_tables.table_id = %s")
    constraint_args.append(args.table_id)
if len(constraints) == 0:
    constraints = ""
else:
    constraints = " AND " + (' and '.join(constraints))

query = "select cikcode, accessionnumber, filing_tables.table_id, table_number, html from filing_tables left join table_director_affinity using (table_id) where table_director_affinity.table_id is null " + constraints

if not args.random_order:
    query += " order by cikcode, accessionnumber, table_number"
if args.stop_after is not None:
    query += f" limit {args.stop_after}"

read_cursor.execute(query, constraint_args)

if args.progress:
    import tqdm
    iterator = tqdm.tqdm(read_cursor, total=read_cursor.rowcount)
else:
    iterator = read_cursor

@functools.lru_cache(20)
def lookup_directors(cikcode, accessionnumber):
    director_read_cursor.execute("select surname from directors_active_on_filing_date where cikcode = %s and accessionnumber = %s",
                                 [cikcode, accessionnumber])
    director_surnames = [director_name_handling.remove_name_suffixes(x[0]) for x in director_read_cursor]
    return director_surnames

def make_word_pool_counter(word_pool):
    word_pool = [x.upper() for x in word_pool]
    def z(series):
        seen_so_far = set()
        for cell in series:
            if type(cell) == float:
                continue
            if type(cell) == int:
                continue
            if cell is None:
                continue
            cell = cell.upper()
            for w in word_pool:
                if w in cell:
                    seen_so_far.update([w])
        return len(seen_so_far)
    return z

for row in iterator:
    cikcode = row[0]
    accessionnumber = row[1]
    table_id = row[2]
    if args.progress:
        iterator.set_description(str(table_id))
    table_number = row[3]
    html = row[4]
    logging.info(f"Processing {cikcode=}, {accessionnumber=}, {table_id=}, {table_number=}")
    director_surnames = lookup_directors(cikcode, accessionnumber)
    word_pool_counter = make_word_pool_counter(director_surnames)
    extraction = Extractor(html)
    extraction.parse()
    the_table = pandas.DataFrame(extraction.return_list())
    #try:
    #    tables = pandas.read_html(html)
    #except ValueError:
    #    logging.info("Could not extract a pandas table")
    #    tables = []
    #if len(tables) == 0:
    #    logging.info("No tables extracted")
    #    write_cursor.execute("insert into table_director_affinity (table_id, number_of_columns, number_of_rows, max_director_names_mentioned_in_any_row, max_director_names_mentioned_in_any_column, number_of_distinct_relevant_director_surnames) values (%s, null, null, null, null, %s)",
    #                     [table_id, len(director_surnames)])
    #    conn.commit()
    #    continue
    # There should only be one table.
    #if len(tables) != 1:
    #    sys.exit(f"There is something very strange in the HTML for table_id = {table_id}. Found {len(tables)} in the html: {html}")
    # the_table = tables[0]
    number_of_rows, number_of_columns = the_table.shape
    if number_of_rows == 0:
        rowish_stuff = None
    else:
        rowish_stuff = the_table.apply(word_pool_counter, axis=1).max()
    if number_of_columns == 0:
        columnish_stuff = None
    else:
        columnish_stuff = the_table.apply(word_pool_counter).max()
    logging.info(f"Inserting {table_id=}, {number_of_columns=}, {number_of_rows=}, {rowish_stuff=}, {columnish_stuff=}, {len(director_surnames)=}")
    write_cursor.execute("insert into table_director_affinity (table_id, number_of_columns, number_of_rows, max_director_names_mentioned_in_any_row, max_director_names_mentioned_in_any_column, number_of_distinct_relevant_director_surnames) values (%s, %s, %s, %s, %s, %s)",
                         [table_id, number_of_columns, number_of_rows, rowish_stuff, columnish_stuff, len(director_surnames)])
    conn.commit()
