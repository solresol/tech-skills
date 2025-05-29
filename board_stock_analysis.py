#!/usr/bin/env python3
"""Analyze relationship between software-skilled directors and stock growth."""

import argparse

import jinja2
import pandas as pd
import numpy as np
import pgconnect
from scipy.stats import mannwhitneyu
from sklearn.linear_model import LinearRegression


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang='en'>
<head>
    <meta charset='UTF-8'>
    <title>Software Skills vs Stock Growth</title>
    <link rel='stylesheet' href='css/style.css'>
</head>
<body>
    <header>
        <h1>Software-Skilled Directors and Stock Growth</h1>
    </header>
    <div class='container'>
        <h2>Mann-Whitney U Test</h2>
        <p>U statistic: {{ u_stat | round(2) }}</p>
        <p>p-value: {{ p_value | round(4) }}</p>
    </div>
    <div class='container'>
        <h2>Regression: Number of Software Directors</h2>
        <p>y = {{ slope_num | round(4) }} * x + {{ intercept_num | round(4) }}</p>
        <p>R<sup>2</sup>: {{ r2_num | round(4) }}</p>
    </div>
    <div class='container'>
        <h2>Regression: Proportion of Software Directors</h2>
        <p>y = {{ slope_prop | round(4) }} * x + {{ intercept_prop | round(4) }}</p>
        <p>R<sup>2</sup>: {{ r2_prop | round(4) }}</p>
    </div>
</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Run stock growth analysis")
    parser.add_argument("--database-config", default="db.conf", help="DB config")
    parser.add_argument(
        "--output-file",
        default="boards-website/analysis.html",
        help="Where to write the HTML results",
    )
    args = parser.parse_args()

    conn = pgconnect.connect(args.database_config)
    query = """
        WITH board_counts AS (
            SELECT cikcode, accessionnumber,
                   COUNT(DISTINCT director_name) AS director_count,
                   SUM(CASE WHEN software_background THEN 1 ELSE 0 END) AS software_count
              FROM director_mentions
             GROUP BY cikcode, accessionnumber
        ),
        filing_prices AS (
            SELECT f.cikcode, f.accessionnumber, f.filingdate, sp.close_price
              FROM filings f
              JOIN cik_to_ticker t ON f.cikcode = t.cikcode
              JOIN stock_prices sp ON sp.ticker = t.ticker AND sp.price_date = f.filingdate
             WHERE f.form = 'DEF 14A'
        )
        SELECT p.cikcode, p.accessionnumber, p.filingdate, p.close_price,
               bc.director_count, bc.software_count
          FROM filing_prices p
          JOIN board_counts bc USING (cikcode, accessionnumber)
         ORDER BY p.cikcode, p.filingdate
    """
    df = pd.read_sql(query, conn)
    conn.close()

    records = []
    prev = {}
    for row in df.itertuples(index=False):
        key = row.cikcode
        if key in prev:
            last = prev[key]
            growth = (row.close_price - last.close_price) / last.close_price * 100.0
            prop = last.software_count / last.director_count if last.director_count else 0.0
            records.append(
                {
                    "growth": growth,
                    "has_software": last.software_count > 0,
                    "num_software": last.software_count,
                    "prop_software": prop,
                }
            )
        prev[key] = row

    res_df = pd.DataFrame.from_records(records)

    with_software = res_df[res_df["has_software"]]["growth"].tolist()
    without_software = res_df[~res_df["has_software"]]["growth"].tolist()

    if with_software and without_software:
        stat_res = mannwhitneyu(with_software, without_software, alternative="two-sided")
        u_stat, p_val = stat_res.statistic, stat_res.pvalue
    else:
        u_stat, p_val = float("nan"), float("nan")

    lr_num = LinearRegression()
    X_num = np.asarray(res_df["num_software"]).reshape(-1, 1)
    y = np.asarray(res_df["growth"])
    lr_num.fit(X_num, y)
    slope_num = lr_num.coef_[0]
    intercept_num = lr_num.intercept_
    r2_num = lr_num.score(X_num, y)

    lr_prop = LinearRegression()
    X_prop = np.asarray(res_df["prop_software"]).reshape(-1, 1)
    lr_prop.fit(X_prop, y)
    slope_prop = lr_prop.coef_[0]
    intercept_prop = lr_prop.intercept_
    r2_prop = lr_prop.score(X_prop, y)

    template = jinja2.Template(HTML_TEMPLATE)
    html = template.render(
        u_stat=u_stat,
        p_value=p_val,
        slope_num=slope_num,
        intercept_num=intercept_num,
        r2_num=r2_num,
        slope_prop=slope_prop,
        intercept_prop=intercept_prop,
        r2_prop=r2_prop,
    )

    with open(args.output_file, "w") as fh:
        fh.write(html)


if __name__ == "__main__":
    main()

