#!/bin/bash

cd $(dirname $0)

uv run batchfetch.py --show-costs
