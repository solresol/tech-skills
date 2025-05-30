#!/bin/bash

cd $(dirname $0)

uv run batchfetch.py --show-costs
uv run process_director_compensation.py --show-costs
uv run compensation_batch_check.py
uv run fetch_prices_for_director_filings.py --stop-after 200
uv run board_stock_analysis.py
uv run boards_website_generator.py
rsync -a boards-website/ merah:/var/www/vhosts/boards.industrial-linguistics.com/htdocs/

uv run make_minified_dump.py
gzip -9 -f techskills.sql
rsync -a techskills.sql.gz merah:/var/www/vhosts/datadumps.ifost.org.au/htdocs/tech-skills/techskills.sql.gz
