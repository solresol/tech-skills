#!/bin/bash

cd $(dirname $0)

# We might as well use the latest version
git pull -q

# This is the core of it
uv run ask_openai_bulk.py --stop-after 100

# I'm not sure if this is working
uv run extract_director_compensation.py --stop-after 110

# Because sector information fails pretty regularly, I often 
# ask codex to populate the mistakes manually. Why I don't
# just get it to do everything is a mystery that past-me is
# holding back on
psql -f manual_sector_inserts.sql

# This fails pretty regularly for a lot of sectors
uv run fetch_all_sectors.py --stop-after 500
