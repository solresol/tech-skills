#!/usr/bin/env python3

# Tries to find a large section of a table where the director names are mentioned,
# and where only two possible values appear in the corresponding column or row.

import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--database-config",
                    default="db.conf",
                    help="Parameters to connect to the database")
parser.add_argument("--table-id", help="Process one table")
parser.add_argument("--stop-after", type=int, help="Process this many tables")
parser.add_argument("--minimum-director-mentions", type=int, default=5)
parser.add_argument("--verbose",
                    action="store_true",
                    help="Lots of debugging messages")
parser.add_argument("--progress",
                    action="store_true",
                    help="Show a progress bar")
parser.add_argument("--dry-run", action="store_true", help="Don't write to the database")
args = parser.parse_args()

import logging
import pgconnect
import sys
import director_name_handling
import director_information_table

if args.dry_run:
    args.verbose = True
    class Pseudo:
        def __init__(self):
            pass
        def execute(self, code, args):
            logging.info(f"Executing: {code} with args {args}")

if args.verbose:
    logging.basicConfig(
        format='%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s',
        level=logging.INFO,
        datefmt='%Y-%m-%d %H:%M:%S')
    logging.info("Starting")

conn = pgconnect.connect(args.database_config)
outer_read_cursor = conn.cursor()
read_cursor = conn.cursor()

if args.dry_run:
    write_cursor = Pseudo()
else:
    write_cursor = conn.cursor()


query = """
select table_id,html,cikcode,accessionnumber, filingdate,
       directors_are_column_headers, directors_are_row_headers
  from table_director_affinity
  join filing_tables using (table_id)
  join filings using (cikcode, accessionnumber)
left join tables_without_mentioned_directors using (table_id)
left join table_deep_details using (table_id)
left join tables_without_content_index using (table_id)
 WHERE (directors_are_column_headers or directors_are_row_headers)
   AND tables_without_mentioned_directors.table_id is null
   AND table_deep_details.table_id is null
   AND tables_without_content_index.table_id is null
   AND max_director_mentions > %s
"""

constraints = []
constraint_args = [args.minimum_director_mentions]

if args.table_id is not None:
    constraints.append('table_id = %s')
    constraint_args.append(args.table_id)

if len(constraints) > 0:
    query += " AND "
    query += " AND ".join(constraints)

if args.stop_after is not None:
    query += " LIMIT " + str(args.stop_after)

logging.info("Running query " + query + " with args " + str(constraint_args))

outer_read_cursor.execute(query, constraint_args)
if args.progress:
    import tqdm
    iterator = tqdm.tqdm(outer_read_cursor, total=outer_read_cursor.rowcount)
else:
    iterator = outer_read_cursor

for outer_row in iterator:
    table_id = outer_row[0]
    if args.progress:
        iterator.set_description(str(table_id))
    logging.debug(f"{table_id=}")
    content = outer_row[1]
    cikcode = outer_row[2]
    accessionnumber = outer_row[3]
    filing_date = outer_row[4]
    directors_are_column_headers = outer_row[5]
    directors_are_row_headers = outer_row[6]
    read_cursor.execute("select director_id, director_name, forename1, surname from directors_active_on_filing_date where filingdate = %s and accessionnumber = %s and cikcode = %s",
                        [filing_date, accessionnumber, cikcode])

    directors = []
    for row in read_cursor:
        directors.append({'director_id': row[0], 'director_name': row[1], 'forename1': row[2], 'surname': row[3]})
    if len(directors) == 0:
        logging.critical(f"Strange, there don't appear to be any directors of {cikcode} at {filing_date}")
        write_cursor.execute("insert into tables_without_mentioned_directors (table_id) values (%s)", [table_id])
        continue

    surnames = {director_name_handling.remove_name_suffixes(d['surname']): d['director_id'] for d in directors}
    upper_surnames = { x.upper(): y for (x,y) in surnames.items() }
    # Note that there is a problem when we have two directors with the same surname. We can't distinguish them.
    grid = director_information_table.DirectorInformationTable(content, 'row' if directors_are_column_headers else 'column',
                                                               surnames.keys())

    if grid.content_index_column is None:
        logging.warning(f"While there are directors mentioned in table {table_id}, there was no content index column")
        write_cursor.execute("insert into tables_without_content_index (table_id) values (%s)", [table_id])
        continue
    write_cursor.execute("insert into table_deep_details (table_id, director_index_position, content_index_position) values (%s,%s,%s)",
                         [table_id, grid.header_idx, grid.content_index_column])
    for director_surname, index_position in grid.director_column_numbers.items():
        director_id = upper_surnames.get(director_surname.upper())
        if director_id is None:
            logging.warning(f"Skipped director surname {director_surname} on table {table_id} because I couldn't match it to a director_id using {upper_surnames}")
            continue
        write_cursor.execute("insert into directors_mentioned_in_table (table_id, director_id, surname_fragment_used, index_position_of_director) values (%s, %s, %s, %s)",
                             [table_id, director_id, director_surname, index_position])
    for index_position, attribute_name in grid.content_index.items():
        if attribute_name is None:
            continue
        write_cursor.execute("insert into attributes_of_directors_mentioned_in_table (table_id, index_position, attribute_name) values (%s, %s, %s)",
                             [table_id, index_position, attribute_name])
    for region_id, region in enumerate(grid.regions_with_few_values()):
        starting_row, ending_row, attribute_name_list, distinct_value_count, distinct_values_set = region
        write_cursor.execute("insert into low_variance_regions_in_table (table_id, region_id, starting_row, ending_row, distinct_value_count) values (%s, %s, %s, %s, %s)",
                             [table_id, region_id, starting_row, ending_row, distinct_value_count])
    for director_surname, director_values in grid.get_values().items():
        director_id = upper_surnames.get(director_surname)
        if director_id is None:
            logging.warning(f"Skipped director surname {director_surname} on table {table_id} because I couldn't match it to a director_id using {upper_surnames}")
            continue
        for content_handle, attribute_value in director_values.items():
            attribute_index_position, attribute_name = content_handle
            if attribute_name is None:
                continue
            write_cursor.execute("insert into denormalised_table (original_table_id, director_id, attribute_index_position, attribute_value) values (%s, %s, %s, %s)",
                                 [table_id, director_id, attribute_index_position, attribute_value])
    conn.commit()

conn.commit()
