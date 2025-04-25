#!/bin/bash

cd $(dirname $0)

uv run ask_openai_bulk.py --stop-after 100
