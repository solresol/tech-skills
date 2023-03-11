#!/bin/bash

./create_prompt.py --new --prompt generation2 --text prompts/generation2/001_preamble.txt
./create_prompt.py --prompt generation2 --company-name
./create_prompt.py --prompt generation2  --text prompts/generation2/003_task.txt
./create_prompt.py --prompt generation2 --list-directors
./create_prompt.py --prompt generation2  --text prompts/generation2/005_director_instructions.txt
./create_prompt.py --prompt generation2 --document
./create_prompt.py --prompt generation2  --text prompts/generation2/007_postfix.txt

