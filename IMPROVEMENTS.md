# IMPROVEMENTS.md

*Analysis date: 2026-07-11*

tech-skills extracts director information (compensation, age, gender, committees) from SEC DEF 14A filings, using OpenAI's batch API against a PostgreSQL database on raksasa, and generates a static website (`boards_website_generator.py`, `network_pages.py`, `boards-website/`). The pipeline runs via `morningcron.sh` / `hourlycron.sh` / `eveningcron.sh`. The repo is functional but has ~7 weeks of uncommitted work sitting in the working tree (last commit 31ba186, files modified 23 May) and a fair amount of accumulated cruft.

## Bugs & Fixes / Unfinished Work

- **Uncommitted budget feature.** `openai_batch_budget.py` and `tests/test_openai_batch_budget.py` are untracked, and `ask_openai_bulk.py`, `extract_director_compensation.py`, `pyproject.toml`, `uv.lock`, `README.md`, `CLAUDE.md` all carry uncommitted modifications (263 insertions). This work — apparently a batch-spend budget cap wired into the bulk-submission scripts — has been dangling since May. Review it, finish it, and commit; a disk failure loses it silently.
- **`STUCK_FILING_INVESTIGATION.md`** documents a resolved incident (batches stuck in error states). If the fixes in `diagnose_error_batches.py` / `batchfetch.py` fully cover it, fold the lessons into README/CLAUDE.md and archive the file; if not, the residual work should be listed explicitly.
- **README is stale and self-contradicting.** It still walks through BoardEx CSV imports and `etl.sql` with inline notes like "[PREVIOUSLY I DID THIS... BUT NOW I THINK I NEED TO BUILD A BOARDEX EQUIVALENT]" and "[LIKEWISE, I DON'T RUN THIS ANY MORE]". Rewrite it to describe the pipeline as it actually runs today (the cron scripts are the source of truth).
- **Step numbering in README** jumps from 5 to 8 — a symptom of the above.

## Security

- **`db.conf` contains a real production password** (`techskills`@raksasa). It is correctly gitignored and not tracked — good — but the credential also appears in shell history/backups risk. Consider `~/.pgpass` (which README already suggests) or at least verify it never appeared in any historical commit (`git log --all -- db.conf` shows nothing tracked; keep it that way).
- **Real email/useragent in `db.conf`** is fine, but README's example block should stay the only committed copy.
- `openai_key.py` reads keys from `~/.openai.boardskills.key` with legacy fallback — sound design; no committed keys found.

## Testing

- Only four test files exist (`tests/`), covering the batch parser, sector fetch, key resolution, and (untracked) budget logic. The riskiest code — `process_director_compensation.py`, `batch_response_parser.py` retry paths, `boards_website_generator.py` (37 KB), `network_pages.py` (41 KB) — is untested. Prioritize: a golden-file test for the batch response parser against a real (sanitized) OpenAI batch output, and a smoke test that the website generator runs against the minified dump.
- `mock_psycopg2/` and `yfinance_stub/` suggest a homegrown mocking approach; document how tests are meant to be run (`uv run pytest`?) in CLAUDE.md.
- `.pytest_cache/` is not gitignored (untracked only by luck) — add it, plus `.venv/` isn't in `.gitignore` either.

## Improvements

- **Repo layout.** ~50 scripts sit flat in the repo root. Group into a package (e.g. `techskills/edgar/`, `techskills/batch/`, `techskills/site/`) or at least subdirectories; the cron scripts would then read as clear pipeline stages.
- **Model pinning.** Commit d3bcd92 bumped batch models to gpt-5.4-mini; model names appear to be hardcoded across scripts — centralize model choice (one config value) so the next bump is a one-line change.
- **`early-exploratory.ipynb` (526 KB) is committed** with outputs. Strip outputs or move it to `documentation/`; it bloats every clone.
- **Cron observability.** `logs/` exists locally; add failure alerting (even a mail on nonzero exit from `eveningcron.sh`) so stuck-batch incidents surface sooner.
- **BoardEx replacement** (README's own note): the plan to "build a BoardEx equivalent" deserves a concrete TODO with schema implications, or should be dropped.

## Housekeeping / Modernization

- Already on `uv` with `pyproject.toml` — good, no requirements.txt to purge. But `pyproject.toml` still says `description = "Add your description here"`; fill it in.
- Delete or gitignore `__pycache__/` at repo root (it's ignored but a stale directory sits there from May).
- `uvbootstrap.py` (55 bytes) and `notes.txt` look vestigial — delete or absorb.
- Several scripts are marked executable but run via `uv run script.py` per the owner's convention; ensure shebangs are consistent (`#!/usr/bin/env -S uv run` or drop them).

## Quick Wins

1. Commit the pending budget work (biggest risk, five minutes).
2. Fix README step numbering and delete the BoardEx-era steps.
3. Add `.pytest_cache/` and `.venv/` to `.gitignore`.
4. Set a real project description in `pyproject.toml`.
5. Strip `early-exploratory.ipynb` outputs.
