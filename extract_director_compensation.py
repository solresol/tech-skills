#!/usr/bin/env python3

import argparse
import pgconnect
import logging
import sys
import os
import openai
from bs4 import BeautifulSoup
import tempfile
import json

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
parser.add_argument("--accession-file",
                    help="File containing accession numbers to process, one per line")
parser.add_argument("--openai-key-file",
                    default="~/.openai.key")
parser.add_argument("--show-prompt", action="store_true", help="Display the prompts that are sent to OpenAI")
parser.add_argument("--show-response", action="store_true", help="Display the response returned by OpenAI")
parser.add_argument("--dry-run", action="store_true", help="Don't send anything to OpenAI")
parser.add_argument("--batch-file", help="Where to put the batch file (default: random tempfile)")
parser.add_argument("--batch-id-save-file", help="What file to put the local batch ID into")

args = parser.parse_args()

if args.verbose:
    logging.basicConfig(
        format='%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s',
        level=logging.INFO,
        datefmt='%Y-%m-%d %H:%M:%S')
    logging.info("Starting")

# Create output file if not specified
if args.batch_file is None:
    tf = tempfile.NamedTemporaryFile(delete=False, mode='w', suffix='.jsonl')
    args.batch_file = tf.name
    tf.close()
else:
    with open(args.batch_file, 'w') as f:
        # reset it to zero
        f.write('')

conn = pgconnect.connect(args.database_config)
read_cursor = conn.cursor()
sentence_cursor = conn.cursor()
write_cursor = conn.cursor()

constraints = []
constraint_args = []
if args.cikcode is not None:
    constraints.append("cikcode = %s")
    constraint_args.append(args.cikcode)
if args.accession_number is not None:
    constraints.append("accessionnumber = %s")
    constraint_args.append(args.accession_number)

# Handle accession numbers from file
accession_numbers = []
if args.accession_file is not None:
    with open(args.accession_file, 'r') as f:
        accession_numbers = [line.strip() for line in f if line.strip()]
    
    if accession_numbers:
        placeholders = ', '.join(['%s'] * len(accession_numbers))
        constraints.append(f"accessionnumber IN ({placeholders})")
        constraint_args.extend(accession_numbers)

if len(constraints) == 0:
    constraints = ""
else:
    constraints = " AND " + (' AND '.join(constraints))

query = """
select cikcode, accessionnumber, content, encoding, content_type, url from
 html_doc_cache join filings on (document_storage_url = url)
 where url not in (select url from director_compensation) 
""" + constraints + " order by cikcode, accessionnumber"

if args.stop_after is not None:
    query += f" limit {args.stop_after}"

read_cursor.execute(query, constraint_args)

write_cursor.execute("Begin transaction;")
write_cursor.execute("insert into director_extract_batches default values returning id")
row = write_cursor.fetchone()
batch_id = row[0]

tools = [{
    "type": "function",
    "function": {
        "name": "show_director_details",
        "description": "Extract director compensation, age, role, gender, and committee memberships from a DEF 14A filing.",
        "parameters": {
            "type": "object",
            "properties": {
                "directors": {
                    "type": "array",
                    "description": "List of directors with their details.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Full name of the director."
                            },
                            "age": {
                                "type": "integer",
                                "description": "Age of the director. If not stated, use 0."
                            },
                            "role": {
                                "type": "string",
                                "description": "Role or position of the director (e.g., Chairman, Independent Director, CEO, etc.)"
                            },
                            "gender": {
                                "type": "string",
                                "description": "Gender of the director (e.g., male, female, non-binary). If uncertain, use 'unknown'."
                            },
                            "committees": {
                                "type": "array",
                                "description": "List of committees the director serves on.",
                                "items": {
                                    "type": "string"
                                }
                            },
                            "compensation": {
                                "type": "integer",
                                "description": "Total annual compensation in USD. If not stated, use 0."
                            },
                            "source_excerpt": {
                                "type": "string",
                                "description": "A short excerpt from the filing providing evidence for the information."
                            }
                        },
                        "required": ["name", "age", "role", "gender", "committees", "compensation", "source_excerpt"]
                    }
                }
            },
            "required": ["directors"]
        }
    }
}]

if args.progress:
    import tqdm
    iterator = tqdm.tqdm(read_cursor, total=read_cursor.rowcount)
else:
    iterator = read_cursor

for cikcode, accession_number, content, encoding, content_type, url in iterator:
    logging.info(f"Processing {cikcode=}, {accession_number=}")
    if args.progress:
        iterator.set_description(f"{cikcode} {accession_number}")
    if content_type == 'text/plain':
        text_version = bytes(content).decode(encoding)
    elif content_type == 'image/gif':
        sys.stderr.write(f"{cikcode} {accession_number} is a gif. {url}\n")
        continue
    elif content_type == 'text/html':
        raw_html = bytes(content).decode(encoding)
        soup = BeautifulSoup(raw_html, "lxml")

        # Remove CSS and JS
        for tag in soup(["style", "script"]):
            tag.decompose()

        # Remove empty tags
        for tag in soup.find_all():
            if not tag.get_text(strip=True):
                tag.decompose()

        # Remove known junk spans (invisible content)
        for span in soup.find_all("span", style=True):
            if span is None:
                # this makes no sense at all
                continue
            if "style" not in span:
                continue
            if span["style"] is None:
                # don't know how this can happen
                continue            
            style = span["style"].lower()
            if "visibility:hidden" in style or "font-size:3pt" in style:
                span.decompose()

        # Remove inline styles and classes
        for tag in soup.find_all(True):
            tag.attrs = {}

        for tag in soup.find_all('font'):
            tag.unwrap()

        for tag in soup.find_all('a'):
            tag.unwrap()        

        text_version = str(soup)
        for tail_tag in ['</td>', '</tr>', '</li>', '</p>']:
            text_version = text_version.replace(tail_tag, '')

        while True:
            space_reduction = text_version.replace('\n\n', '\n')
            if space_reduction == text_version:
                break
            text_version = space_reduction
    else:
        sys.exit(f"Don't know how to handle {cikcode=} {accession_number=} because {content_type=}")

        
    system_prompt = """Extract information about all directors listed in this DEF 14A filing. For each director, provide:

1. Their full name
2. Their age (if mentioned)
3. Their role or position (e.g., Chairman, Independent Director, CEO, etc.)
4. Their gender (male, female, or non-binary; use 'unknown' if uncertain)
5. All committees they serve on (e.g., Audit, Compensation, Governance, etc.)
6. Their total annual compensation in USD
7. A relevant excerpt from the filing that supports this information

For determining gender:
- Look for pronouns (he/him, she/her, they/them) used in descriptions of the director
- Consider traditional gender associations with first names
- Look for titles like Mr., Mrs., Ms., etc.
- If the gender cannot be determined from the document, use 'unknown'

If any information is not available for a director, use appropriate default values (0 for numeric fields, empty array for committees, 'unknown' for gender if not determinable, etc.).
"""

    
    
    batch_text = {
        "custom_id": url,
        "method": "POST",
        "url": "/chat/completions",
        "body": {
            "model": "gpt-4.1-mini",
            "messages": [{"role": "system", "content": system_prompt}, { "role": "user", "content": text_version}],
            "temperature": 0,
            "tools": tools,
            "tool_choice": {"type": "function", "function": {"name": "show_director_details"}}
        }
    }

    # Write to batch file
    with open(args.batch_file, 'a') as f:
        f.write(json.dumps(batch_text) + "\n")

    write_cursor.execute("insert into director_compensation (url, batch_id) values (%s, %s)", [url, batch_id])


if args.dry_run:
    conn.rollback()
    sys.exit(0)

# Submit the batch to OpenAI
api_key = open(os.path.expanduser(args.openai_key_file)).read().strip()
client = openai.OpenAI(api_key=api_key)


batch_input_file = client.files.create(
    file=open(args.batch_file, "rb"),
    purpose="batch"
)

result = client.batches.create(
    input_file_id=batch_input_file.id,
    endpoint="/chat/completions",
    completion_window="24h",
    metadata={
        "description": f"director_compensation batch {batch_id}",
        "local_batch_id": f"{batch_id}"
    }
)



write_cursor.execute(
    "update director_extract_batches set openai_batch_id = %s, when_sent = current_timestamp where id = %s",
    [result.id, batch_id]
)

if write_cursor.rowcount != 1:
    sys.exit(f"Unexpectedly updated {write_cursor.rowcount} rows when we set the openai_batch id to {result.id} for batch {batch_id}")

conn.commit()

if args.batch_id_save_file:
    with open(args.batch_id_save_file, 'w') as bisf:
        bisf.write(f"{batch_id}")