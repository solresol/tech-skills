#!/usr/bin/env python3

import argparse
import pgconnect
import logging
import sys

parser = argparse.ArgumentParser(description="Extract latest accession numbers per CIK from processed filings")
parser.add_argument("--database-config",
                    default="db.conf",
                    help="Parameters to connect to the database")
parser.add_argument("--output-file",
                    default="latest_accessions.txt",
                    help="File to output the latest accession numbers")
parser.add_argument("--verbose",
                    action="store_true",
                    help="Lots of debugging messages")
args = parser.parse_args()

if args.verbose:
    logging.basicConfig(
        format='%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s',
        level=logging.INFO,
        datefmt='%Y-%m-%d %H:%M:%S')
    logging.info("Starting extraction of latest accession numbers")

try:
    conn = pgconnect.connect(args.database_config)
    cursor = conn.cursor()
    
    # Query to get the latest filing per CIK that has been processed by ask_openai_bulk.py
    # This joins director_extraction_raw with filings to get filing dates
    # Then selects the most recent filing per CIK
    query = """
    WITH latest_filings AS (
        SELECT 
            f.cikcode,
            f.accessionnumber,
            f.filingdate,
            f.form,
            ROW_NUMBER() OVER (PARTITION BY f.cikcode ORDER BY f.filingdate DESC) as row_num
        FROM 
            director_extraction_raw der
            JOIN filings f ON der.cikcode = f.cikcode AND der.accessionnumber = f.accessionnumber
        WHERE 
            f.form = 'DEF 14A'  -- Only include DEF 14A filings
    )
    SELECT cikcode, accessionnumber, filingdate
    FROM latest_filings
    WHERE row_num = 1
    ORDER BY cikcode;
    """
    
    cursor.execute(query)
    results = cursor.fetchall()
    
    if args.verbose:
        logging.info(f"Found {len(results)} latest filings")
    
    # Write accession numbers to the output file
    with open(args.output_file, 'w') as f:
        for cikcode, accession_number, filing_date in results:
            f.write(f"{accession_number}\n")
            if args.verbose:
                logging.info(f"CIK: {cikcode}, Accession: {accession_number}, Date: {filing_date}")
    
    print(f"Successfully extracted {len(results)} latest accession numbers to {args.output_file}")
    
except Exception as e:
    print(f"Error: {str(e)}", file=sys.stderr)
    sys.exit(1)
finally:
    if 'conn' in locals():
        conn.close()