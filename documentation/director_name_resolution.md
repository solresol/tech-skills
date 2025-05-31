# Resolving Director Names with Variations

## Overview
SEC filings may reference the same director under slightly different names. Variations can include middle initials, suffixes ("Jr", "III"), or minor spelling differences. Without consolidation these variants inflate counts and make it difficult to track board service over time.

This document proposes a strategy for unifying director references and maintaining a canonical identifier.

## Goals
1. Detect when two extracted names likely refer to the same individual.
2. Store all observed variants while assigning a unique ID per director.
3. Allow manual or semi-automated resolution for ambiguous cases.

## Approach
### 1. Pre-processing
- Normalise accents and punctuation.
- Strip common prefixes (e.g. "Mr", "Ms") using the `remove_name_suffixes` helper already in the code base.
- Detect and isolate suffixes such as "Jr", "Sr", "II", "III".
- Convert everything to upper case for comparison while preserving the original form for display.

### 2. Candidate Matching
For every new name, generate possible matches against known directors using a set of features:
- Trigram overlap or other n‑gram similarity between normalised names.
- Levenshtein distance of surnames and full names.
- Presence or mismatch of suffixes (e.g. "Sr" vs "Jr").
- Gender prediction to reduce false matches when surnames change.
- Board context: two names serving on the same company in adjacent years are more likely to be the same person.
The features feed into a classifier (logistic regression or random forest) trained on manually labelled pairs (same vs different). The classifier outputs a probability that two names refer to the same individual.

### 3. LLM Assisted Resolution
Pairs with probabilities in an uncertain range (e.g. 0.4–0.6) can be escalated to a large language model. The LLM receives excerpts from biographies or filings describing each director and returns a judgement on whether they match. This step reduces manual review while still capturing harder cases.

### 4. Database Schema
Two new tables are proposed:
- **directors**
  - `id` SERIAL PRIMARY KEY
  - `canonical_name` TEXT
  - optional biography fields (date of birth, etc.)
- **director_name_aliases**
  - `id` SERIAL PRIMARY KEY
  - `director_id` INT REFERENCES directors(id)
  - `alias` TEXT
  - `source` TEXT (filing URL or dataset)
  - UNIQUE(director_id, alias)

During extraction, each raw name is looked up via the classifier. If a match above a threshold is found, the alias is linked to that director_id. Otherwise a new director row is created.

### 5. External Identifiers
EDGAR itself does not provide a persistent director ID. BoardEx and similar datasets sometimes assign their own IDs, which could be stored as additional columns in the `directors` table when available. Mapping to such external IDs can help merge data from multiple sources.

### 6. Implementation Plan
1. Label a training set of name pairs using existing extractions.
2. Build and evaluate the classifier on those pairs.
3. Extend the extraction pipeline to consult the classifier when new names appear and insert into the new tables.
4. Add optional LLM resolution for borderline cases.
5. Provide utilities to merge or split director IDs if errors are discovered later.

### 7. Future Work
- Use network analysis of board co-membership to reinforce matches.
- Track history of name changes (e.g. marriage) by analysing biography text.
- Periodically retrain the classifier as more labelled data becomes available.

### Provided Tools
Two helper programs implement the above process:

- `train_name_matcher.py` trains a logistic regression model from a CSV file of
  labelled name pairs (`name1,name2,label`). The resulting model is saved to a
  file for later use.
- `resolve_director_names.py` applies a trained model to names extracted in the
  `director_mentions` view and populates the new `directors` and
  `director_name_aliases` tables. It falls back to simple normalisation when no
  model is supplied.

