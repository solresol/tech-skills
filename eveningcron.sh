#!/bin/bash

cd $(dirname $0)

uv run batchfetch.py --show-costs
uv run process_director_compensation.py --show-costs
uv run boards_website_generator.py
rsync -a boards-website/ merah:/var/www/vhosts/boards.industrial-linguistics.com/htdocs/
