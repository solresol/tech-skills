#!/usr/bin/env python3

import argparse
import os
import sys
import openai
import pgconnect
import time

parser = argparse.ArgumentParser()
parser.add_argument("--database-config",
                    default="db.conf",
                    help="Parameters to connect to the database")
parser.add_argument("--openai-api-key", default=os.path.expanduser("~/.openai.key"))
parser.add_argument("--only-batch", type=int, help="The batch ID to look at")
parser.add_argument("--monitor", action="store_true", help="Monitor in a loop until the status is 'completed'. Only makes sense with --only-batch")
args = parser.parse_args()

api_key = open(args.openai_api_key).read().strip()
client = openai.OpenAI(api_key=api_key)

conn = pgconnect.connect(args.database_config)
cursor = conn.cursor()
update_cursor = conn.cursor()

# Updated query for director compensation batches
query = """
    SELECT director_extract_batches.id, openai_batch_id, COUNT(url) 
    FROM director_extract_batches 
    JOIN director_compensation ON (batch_id = director_extract_batches.id) 
    WHERE when_sent IS NOT NULL 
    AND when_retrieved IS NULL
"""

if args.only_batch:
    query += f"AND director_extract_batches.id = {int(args.only_batch)} "
query += "GROUP BY director_extract_batches.id, openai_batch_id"

if args.monitor:
    import tqdm
    progress = None

while True:
    cursor.execute(query)
    work_to_be_done = False

    for local_batch_id, openai_batch_id, number_of_files in cursor:
        openai_result = client.batches.retrieve(openai_batch_id)
        if openai_result.status == 'completed':
            work_to_be_done = True
        
        if openai_result.status in ['in_progress', 'completed']:
            update_cursor.execute(
                "INSERT INTO batchprogress (batch_id, number_completed, number_failed) VALUES (%s,%s,%s)",
                [local_batch_id, openai_result.request_counts.completed, openai_result.request_counts.failed]
            )
            conn.commit()
        
        if args.monitor:
            if progress is None:
                progress = tqdm.tqdm(total=number_of_files)
            progress.set_description(openai_result.status)
            if openai_result.status in ['in_progress', 'completed']:
                progress.update(openai_result.request_counts.completed - progress.n)
            if openai_result.status == 'completed':
                break
            time.sleep(15)
            continue
        
        print(f"""## {openai_result.metadata.get('description')}
      Num files: {number_of_files}
       Local ID: {local_batch_id}
       Returned: {openai_result.metadata.get('local_batch_id')}
       Batch ID: {openai_batch_id}
        Created: {time.asctime(time.localtime(openai_result.created_at))}
         Status: {openai_result.status}""")
        
        if openai_result.errors:
            print("      Errors: ")
            for err in openai_result.errors.data:
                print(f"         - {err.code} on line {err.line}: {err.message}")
        
        if openai_result.request_counts:
            print(f"       Progress: {openai_result.request_counts.completed}/{openai_result.request_counts.total}")
            print(f"       Failures: {openai_result.request_counts.failed}")
        print()

    if not args.monitor:
        break
    if work_to_be_done:
        break

if work_to_be_done:
    sys.exit(0)
else:
    sys.exit(1)