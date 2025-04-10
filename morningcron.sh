#!/bin/bash

cd $(dirname $0)

uv run ask_openai_batch.py --stop-after 100
