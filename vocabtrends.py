#!/usr/bin/env python3

import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--database-config",
                    default="db.conf",
                    help="Parameters to connect to the database")
parser.add_argument("--cikcode",
                    type=int,
                    help="Only process documents from this cikcode")
parser.add_argument("--csv-output",
                    help="Output to this CSV file")
args = parser.parse_args()

import pgconnect
import logging
import sys
import collections
import json
import pandas
import sklearn.linear_model
import sklearn.feature_extraction

conn = pgconnect.connect(args.database_config)
read_cursor = conn.cursor()


constraints = []
constraint_args = []
if args.cikcode is not None:
    constraints.append("cikcode = %s")
    constraint_args.append(args.cikcode)
if len(constraints) > 0:
    constraints = " WHERE " + " and ".join(constraints)
else:
    constraints = ""

query = """
select extract(year from filingDate), sentence
from experience_sentences
join nes_ranges using (nes_range_id)
join filings using (cikcode, accessionNumber)
""" + constraints + " order by 1"

read_cursor.execute(query, constraint_args)

text_blobs = collections.defaultdict(list)
for year, sentence in read_cursor:
    text_blobs[year].append(sentence)

years = pandas.DataFrame({'year': pandas.Series(list(text_blobs.keys()))})

texts_by_year = pandas.Series({ year: "\n".join(text_blobs[year]) for year in text_blobs }).reset_index()
texts_by_year.rename(columns={'index': 'year', 0: 'raw_text'}, inplace=True)

cvec = sklearn.feature_extraction.text.CountVectorizer(stop_words='english', ngram_range=(1,2))
vocab_array = cvec.fit_transform(texts_by_year.raw_text)

trend = sklearn.linear_model.LinearRegression()
vocab_trend = {}
for i,phrase in enumerate(cvec.get_feature_names_out()):
    trend.fit(years,vocab_array[:,i].toarray().flatten())
    vocab_trend[phrase] = trend.coef_[0]

vocab_trend = pandas.DataFrame({'growth_rate': pandas.Series(vocab_trend)})
vocab_trend.sort_values('growth_rate', inplace=True)

if args.csv_output:
    vocab_trend.to_csv(args.csv_output)

print(vocab_trend.nsmallest(20, 'growth_rate'))
print(vocab_trend.nlargest(20, 'growth_rate'))
