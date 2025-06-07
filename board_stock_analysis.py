#!/usr/bin/env python3
"""Analyze relationship between software-skilled directors and stock growth."""

import argparse

import os

import jinja2
import pandas as pd
import numpy as np
import pgconnect
import configparser
import warnings

try:
    import sqlalchemy
except ImportError:  # pragma: no cover - optional dependency may be missing
    sqlalchemy = None
from scipy.stats import mannwhitneyu, linregress
import matplotlib.pyplot as plt
import seaborn as sns


def format_p(value: float) -> str:
    """Return a nicely formatted p-value."""
    if pd.isna(value):
        return "nan"
    return f"{value:.4f}" if value >= 1e-4 else f"{value:.2e}"


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
        <p>p-value: {{ p_value }}</p>
        <img src='growth_violin.png' alt='Growth distribution by board type'>
    </div>
    <div class='container'>
        <h2>Regression: Number of Software Directors</h2>
        <p>y = {{ slope_num | round(4) }} * x + {{ intercept_num | round(4) }}</p>
        <p>R<sup>2</sup>: {{ r2_num | round(4) }}</p>
        <p>p-value: {{ p_num }}</p>
        <img src='num_regression.png' alt='Regression number of software directors'>
    </div>
    <div class='container'>
        <h2>Regression: Proportion of Software Directors</h2>
        <p>y = {{ slope_prop | round(4) }} * x + {{ intercept_prop | round(4) }}</p>
        <p>R<sup>2</sup>: {{ r2_prop | round(4) }}</p>
        <p>p-value: {{ p_prop }}</p>
        <img src='prop_regression.png' alt='Regression proportion of software directors'>
    </div>
    <div class='container'>
        <h2>Sector Results</h2>
        <table>
            <tr><th>Sector</th><th>U statistic</th><th>p-value</th></tr>
            {% for row in sector_stats %}
            <tr><td>{{ row.sector or 'Unknown' }}</td><td>{{ row.u_stat|round(2) }}</td><td>{{ row.p_str }}</td></tr>
            {% endfor %}
        </table>
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

    output_dir = os.path.dirname(args.output_file)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    config = configparser.ConfigParser()
    config.read(args.database_config)

    dbinfo = config["database"]
    dbname = dbinfo["dbname"]
    user = dbinfo["user"]
    password = dbinfo["password"]
    host = dbinfo["hostname"]
    port = dbinfo.get("port", 5432)

    query = """
        WITH board_counts AS (
            SELECT cikcode, accessionnumber,
                   COUNT(DISTINCT director_name) AS director_count,
                   SUM(CASE WHEN software_background THEN 1 ELSE 0 END) AS software_count
              FROM director_mentions
             GROUP BY cikcode, accessionnumber
        ),
        filing_prices AS (
            SELECT f.cikcode, f.accessionnumber, f.filingdate, sp.close_price, t.ticker
              FROM filings f
              JOIN cik_to_ticker t ON f.cikcode = t.cikcode
              JOIN stock_prices sp ON sp.ticker = t.ticker AND sp.price_date = f.filingdate
             WHERE f.form = 'DEF 14A'
        )
        SELECT p.cikcode, p.accessionnumber, p.filingdate, p.close_price,
               bc.director_count, bc.software_count, ts.sector
          FROM filing_prices p
          JOIN board_counts bc USING (cikcode, accessionnumber)
          LEFT JOIN ticker_sector ts ON p.ticker = ts.ticker
         ORDER BY p.cikcode, p.filingdate
    """
    if sqlalchemy is not None:
        conn_uri = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}"
        engine = sqlalchemy.create_engine(conn_uri)
        df = pd.read_sql(query, engine)
        engine.dispose()
    else:
        conn = pgconnect.connect(args.database_config)
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="pandas only supports SQLAlchemy connectable",
            )
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
                    "sector": row.sector,
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
    p_val_str = format_p(p_val)

    y = np.asarray(res_df["growth"])

    lr_num = linregress(res_df["num_software"], y)
    slope_num = lr_num.slope
    intercept_num = lr_num.intercept
    r2_num = lr_num.rvalue**2
    p_num = lr_num.pvalue
    p_num_str = format_p(p_num)

    lr_prop = linregress(res_df["prop_software"], y)
    slope_prop = lr_prop.slope
    intercept_prop = lr_prop.intercept
    r2_prop = lr_prop.rvalue**2
    p_prop = lr_prop.pvalue
    p_prop_str = format_p(p_prop)

    sector_stats = []
    for sector, gdf in res_df.groupby("sector"):
        ws = gdf[gdf["has_software"]]["growth"]
        wo = gdf[~gdf["has_software"]]["growth"]
        if ws.empty or wo.empty:
            continue
        stat = mannwhitneyu(ws, wo, alternative="two-sided")
        sector_stats.append(
            {
                "sector": sector,
                "u_stat": stat.statistic,
                "p_value": stat.pvalue,
                "p_str": format_p(stat.pvalue),
            }
        )

    # Generate violin plot for growth distributions
    fig, ax = plt.subplots()
    sns.violinplot(x="has_software", y="growth", data=res_df, ax=ax)
    ax.set_xlabel("Has Software Director")
    ax.set_ylabel("Stock Growth (%)")
    violin_path = os.path.join(output_dir, "growth_violin.png")
    fig.savefig(violin_path)
    plt.close(fig)

    # Scatter/regression plots
    fig, ax = plt.subplots()
    sns.regplot(x="num_software", y="growth", data=res_df, ci=None, ax=ax)
    ax.set_xlabel("Number of Software Directors")
    ax.set_ylabel("Stock Growth (%)")
    num_reg_path = os.path.join(output_dir, "num_regression.png")
    fig.savefig(num_reg_path)
    plt.close(fig)

    fig, ax = plt.subplots()
    sns.regplot(x="prop_software", y="growth", data=res_df, ci=None, ax=ax)
    ax.set_xlabel("Proportion of Software Directors")
    ax.set_ylabel("Stock Growth (%)")
    prop_reg_path = os.path.join(output_dir, "prop_regression.png")
    fig.savefig(prop_reg_path)
    plt.close(fig)

    template = jinja2.Template(HTML_TEMPLATE)
    html = template.render(
        u_stat=u_stat,
        p_value=p_val_str,
        slope_num=slope_num,
        intercept_num=intercept_num,
        r2_num=r2_num,
        p_num=p_num_str,
        slope_prop=slope_prop,
        intercept_prop=intercept_prop,
        r2_prop=r2_prop,
        p_prop=p_prop_str,
        sector_stats=sector_stats,
    )

    with open(args.output_file, "w") as fh:
        fh.write(html)


if __name__ == "__main__":
    main()

