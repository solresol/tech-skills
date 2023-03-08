#!/usr/bin/env python3

import sys

def make_prompt(cursor, prompt_id, director_names=None, company_name=None, document=None):
    cursor.execute("select section_number, insert_raw_text, raw_text, insert_company_name, insert_directors, insert_document from prompt_sections where prompt_id = %s order by section_number",
                   [prompt_id])
    answer = ""
    for row in cursor:
        section_number, insert_raw_text, raw_text, insert_company_name, insert_directors, insert_document = row
        if insert_raw_text:
            answer += raw_text
            continue
        if insert_company_name:
            answer += company_name
            continue
        if insert_directors:
            answer += director_names
            continue
        if insert_document:
            answer += document
            continue
        sys.exit(f"Could not process section number = {section_number} of prompt {prompt_id}; no action is defined somehow.")
    return answer

if __name__ == "__main__":
    import argparse
    import pgconnect
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-config",
                        default="db.conf",
                        help="Parameters to connect to the database")
    parser.add_argument("--prompt-id",
                        required=True,
                        help="Use this prompt_id")

    args = parser.parse_args()
    conn = pgconnect.connect(args.database_config)
    cursor = conn.cursor()
    print(make_prompt(cursor, args.prompt_id, "{DIRECTOR NAMES GO HERE}", "{COMPANY NAME GOES HERE}", "{DOCUMENT BODY GOES HERE}"))
