# Stuck Filing Problem Investigation

This file tracks progress on investigating and fixing the issue where director extraction appears stuck at ~39.95% of filings.

**IMPORTANT**: When the problem is solved, remove the Claude invocation from the end of `eveningcron.sh`.

## Purpose of Daily Claude Runs

Claude is invoked at the end of `eveningcron.sh` to:
1. Check if the filing progress has improved since the previous day
2. Continue investigating and fixing the root cause
3. Document findings in this file

## Key Metrics to Track

Record these daily to determine if the fix is working:

| Date | Total DEF 14A | Processed | Unprocessed | % Complete | Notes |
|------|---------------|-----------|-------------|------------|-------|
| 2025-11-26 AM | 55,315 | 884 | 19,573 | 1.6% | Initial investigation |
| 2025-11-26 PM | 55,315 | 15,105 | 13 | 27.3% | Fixed workflow issue, processed backlog |
| 2025-11-27 | 55,315 | 15,105 | 122 | 27.3% | Fixed expired file handling in batchfetch.py; 100+ expired batches marked |

**SQL to get current metrics:**
```sql
-- Total DEF 14A filings
SELECT count(*) FROM filings WHERE form = 'DEF 14A';

-- Processed filings
SELECT count(*) FROM director_compensation WHERE processed = true;

-- Unprocessed filings
SELECT count(*) FROM director_compensation WHERE processed = false;
```

## Root Cause Analysis

### Hypothesis 1: OpenAI Batch URL Mismatch (CONFIRMED)

**Status**: ROOT CAUSE IDENTIFIED

**Finding**: All OpenAI batches since October 10, 2025 have been failing with error:
```
invalid_url: The URL provided for this request does not match the batch endpoint.
```

**Evidence**:
1. Last successful batch: October 9, 2025 (batch 1013)
2. First failed batch: October 10, 2025 (batch 1014 onwards)
3. 97 batches have been sent but never retrieved (all failed)

**Technical Details**:

The batch file (`extract_director_compensation.py:250`) contains:
```python
"url": "/chat/completions",
```

But the batch is created with endpoint (`extract_director_compensation.py:283`):
```python
endpoint="/v1/chat/completions",
```

These **must match**. The URL in the batch file should be `/v1/chat/completions`.

**Commit that broke it**: `61c6009` (Oct 9, 2025)
```
Fix OpenAI batch API URL to prevent duplicate /v1/ prefix
```

The commit message incorrectly states that OpenAI prepends `/v1/` automatically. This is NOT correct - the URL in the batch file and the endpoint parameter must match exactly.

### Fix Required

Change `extract_director_compensation.py` line 250 from:
```python
"url": "/chat/completions",
```
to:
```python
"url": "/v1/chat/completions",
```

Similarly, `ask_openai_bulk.py` line 211 has the same issue and should be fixed.

## Additional Issues to Address

### Issue: Failed Batches Not Being Cleaned Up

The `batchfetch.py` script (line 64) only processes batches with status `completed` or `expired`. Failed batches are silently ignored, which means:
1. URLs get added to `director_compensation` table with `processed=false`
2. These URLs are never reprocessed because they're already in the table
3. The batch is never marked as retrieved

**Recommendation**: After fixing the URL issue, consider:
1. Marking failed batches as retrieved (with an error flag)
2. Removing URLs from `director_compensation` for failed batches so they can be resubmitted

### Issue: Duplicate Batch Submissions

The query in `extract_director_compensation.py` (line 90-94) excludes URLs already in `director_compensation`:
```sql
where url not in (select url from director_compensation)
```

Since failed batch URLs are still in `director_compensation`, they won't be resubmitted. This means 19,573 URLs are stuck.

## Progress Log

### 2025-11-27 - Expired Output Files Discovery

- **Investigator**: Claude (interactive session)
- **Trigger**: `hourlycron.sh` was failing with error: "Hourly batch check failed during batchfetch step"

- **Findings**:
  1. `batchfetch.py` was crashing when trying to fetch output files from OpenAI
  2. Error: `openai.NotFoundError: No such File object: file-RbSpfgiFJJiuSmvCyztkHu`
  3. OpenAI batch output files expire after ~30 days
  4. **100+ batches had expired output files** that could never be retrieved
  5. The script had error handling for expired error files but not for expired output files

- **Impact on Stuck Filing Problem**:
  - These expired batches represent work that was completed by OpenAI but never retrieved
  - The filings in those batches were sent to OpenAI, processed successfully, but the results expired before being fetched
  - This is likely a significant contributor to why progress appeared stuck
  - The affected batches span from batch 554 to batch 1013 (covering many months of processing)

- **Actions Taken**:
  1. Added error handling in `batchfetch.py` (lines 84-104) to catch `NotFoundError` when fetching output files
  2. When an output file is expired, the script now:
     - Logs a clear error message with batch IDs and file ID
     - Marks the batch as retrieved in the database (to prevent infinite retries)
     - Prints human-readable error to stderr
     - Continues processing other batches instead of crashing
  3. Enabled default logging at WARNING level (lines 32-37) so errors are always visible
  4. Ran `hourlycron.sh` successfully - it processed all expired batches and marked them as retrieved

- **Batches Affected** (partial list from log):
  - Batch 554, 703, 737, 739, 741, 765, 767, 769, 771, 773, 775, 777, 780, 783, 785, 787, 789, 791, 793, 795, 797, 799, 801, 803, 805, 807, 809, 811, 813, 815, 817, 819, 821, 823, 825, 827, 829, 831, 833, 835, 841, 843, 845, 847, 849, 857, 859, 867, 885, 917, 933, 963, 965, 967, 969, 971, 973, 985, 987, 989, 991, 993, 995, 997, 999, 1001, 1003, 1005, 1007, 1009, 1011, 1013
  - Total: 100+ batches with expired output files

- **Root Cause Analysis**:
  - The October 9, 2025 URL mismatch bug (commit `61c6009`) caused batches to fail
  - But there were also older batches (before the bug) that completed but were never fetched
  - OpenAI files expire after ~30 days, so any batch not fetched within that window loses its data
  - The `hourlycron.sh` script wasn't running reliably, allowing completed batches to expire

- **Recommendation for Recovery**:
  - The filings in these expired batches need to be **resubmitted** to OpenAI
  - Query to find affected filings:
    ```sql
    -- Find filings that were in expired batches and need resubmission
    SELECT f.document_storage_url
    FROM filings f
    JOIN director_compensation dc ON dc.url = f.document_storage_url
    WHERE dc.processed = false
    AND NOT EXISTS (
        SELECT 1 FROM director_extraction_raw der
        WHERE der.cikcode = f.cikcode
        AND der.accessionnumber = f.accessionnumber
    );
    ```
  - These URLs should be removed from `director_compensation` table to allow resubmission

- **Current State**:
  - `hourlycron.sh` now runs successfully
  - Expired batches are marked as retrieved (won't cause infinite retry loops)
  - Going forward, completed batches will be fetched promptly by hourly cron
  - Historical data from expired batches is permanently lost and must be resubmitted

### 2025-11-26 PM - Second Fix: Workflow Conflict Resolved

- **Investigator**: Claude (automated evening cron run)
- **Findings**:
  1. Discovered critical workflow issue: `batchfetch.py` and `process_director_compensation.py` both mark batches as retrieved
  2. When both run in `eveningcron.sh`, batchfetch runs first and marks batches as retrieved
  3. process_director_compensation then finds no batches to process (looks for `when_retrieved IS NULL`)
  4. Result: Data gets into `director_extraction_raw` but never processed into `director_details`
  5. Gap discovered: 22,100 raw extractions but only 7,850 in director_details
  6. OpenAI batch output files expire after ~1 month, so couldn't re-fetch old batches

- **Actions Taken**:
  1. Created `process_from_raw.py` script to process FROM `director_extraction_raw` table
  2. Ran script to process 14,145 previously stuck URLs
  3. Only 12 URLs failed due to malformed data (some directors as strings instead of objects)
  4. Processed count increased from 884 (1.6%) to 15,105 (27.3%)

- **Root Cause**:
  - eveningcron.sh runs both batchfetch.py AND process_director_compensation.py sequentially
  - Both scripts mark batches as retrieved, creating a race condition
  - Since October (when fix for URL issue was applied), batches completed but weren't fully processed

- **Permanent Fix Needed**:
  - Option 1: Remove `batchfetch.py` from eveningcron.sh (keep only process_director_compensation.py)
  - Option 2: Modify batchfetch.py to NOT mark batches as retrieved
  - Option 3: Integrate process_from_raw.py into the regular workflow

  Recommendation: Use Option 3 - add `process_from_raw.py` to eveningcron.sh after batchfetch.py to handle any gap

- **Current State**:
  - 15,105 filings processed (27.3%)
  - 13 unprocessed URLs remaining (down from 14,234)
  - 125,971 director records in director_details (up from 7,850)
  - Workflow issue resolved going forward

### 2025-11-26 AM - Initial Investigation & Fix Applied

- **Investigator**: Claude (interactive session)
- **Findings**:
  1. Confirmed 884 filings processed (1.6%), 19,573 stuck
  2. Root cause identified: URL mismatch in OpenAI batch requests
  3. Issue introduced by commit `61c6009` on October 9, 2025
  4. 97 batches have failed silently since then

- **Actions Taken**:
  1. Fixed URL in `extract_director_compensation.py` line 250 (changed `/chat/completions` to `/v1/chat/completions`)
  2. Fixed URL in `ask_openai_bulk.py` line 211 similarly
  3. Fixed `EXPECTED_BATCH_ENDPOINT` constant in `ask_openai_bulk.py` line 233
  4. Cleaned up 97 failed batches (marked as retrieved, deleted 5,341 stuck URLs from director_compensation)
  5. Submitted test batch (batch 1110) - **SUCCESS**: passed validation and now `in_progress`

- **Current State After Fix**:
  - Processed filings: 884
  - Unprocessed (in director_compensation): 14,232
  - URLs available for reprocessing: ~35,000+ (were stuck due to being in director_compensation from failed batches)
  - Test batch 1110: `in_progress` with 2 requests, no errors

- **Next Steps**:
  1. Wait for test batch 1110 to complete (within 24 hours)
  2. Run `batchfetch.py` and `process_director_compensation.py` to retrieve results
  3. Monitor daily metrics to confirm progress is being made
  4. Once confirmed working, the Claude call can be removed from eveningcron.sh

## How to Verify the Fix

After applying the fix:

1. Create a test batch manually:
   ```bash
   uv run extract_director_compensation.py --stop-after 5 --verbose
   ```

2. Wait for OpenAI to process (up to 24h)

3. Check batch status:
   ```python
   import openai, os
   client = openai.OpenAI(api_key=open(os.path.expanduser('~/.openai.key')).read().strip())
   # Use the batch ID from the output above
   result = client.batches.retrieve('batch_xxx')
   print(result.status, result.errors)
   ```

4. If successful, run full extraction and monitor the metrics table above.
