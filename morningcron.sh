#!/bin/bash

cd $(dirname $0)

uv run ask_openai_bulk.py --stop-after 100
uv run extract_director_compensation.py --stop-after 110
uv run fetch_all_sectors.py --stop-after 500
