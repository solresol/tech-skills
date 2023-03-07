#!/bin/bash

./create_prompt.py --new --prompt initial-prototype-1 --text prompts/initial-prototype-1/001_prefix.txt
./create_prompt.py --prompt initial-prototype-1 --document
./create_prompt.py --prompt initial-prototype-1  --text prompts/initial-prototype-1/003_postfix.txt
