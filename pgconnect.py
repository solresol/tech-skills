#!/usr/bin/env python3

"""If you run this file as a program, it will check whether your db.conf works.
Generally you will use it as a module, and call the connect() function"""

import psycopg2
import configparser

def connect(config_filename):
    # To-do: we should also check environment variables
    config = configparser.ConfigParser()
    config.read(config_filename)
    dbname = config['database']['dbname']
    user = config['database']['user']
    password = config['database']['password']
    host = config['database']['hostname']
    port = config['database'].get('port', 5432)
    conn = psycopg2.connect(f'dbname={dbname} user={user} password={password} host={host} port={port}')
    return conn

if __name__ == '__main__':
    import argparse
    import sys
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-config",  default="db.conf",
                        help="Parameters to connect to the database")
    args = parser.parse_args()
    conn = connect(args.database_config)
    cursor = conn.cursor()
    cursor.execute("select 1+1")
    output = cursor.fetchone()
    if output is None:
        sys.exit("Could not even query 1+1")
    if output[0] != 2:
        sys.exit("Database cannot do arithmetic")
    print("All clear. Database connection seems sane.")
