from datetime import date

import pandas as pd

from opendirector_prices import (
    Security,
    history_rows,
    load_seed,
    optional_float,
    parse_asx_directory_csv,
    select_securities,
)


def test_seed_is_well_formed():
    entries = load_seed("opendirector_asx_seed.json")
    assert len(entries) == 27
    assert {entry["provider_symbol"] for entry in entries} >= {
        "WBC.AX",
        "RIO.AX",
        "TLS.AX",
    }


def test_history_rows_preserve_raw_and_adjusted_prices():
    index = pd.DatetimeIndex(
        ["2021-09-27T00:00:00+10:00", "2021-09-28T00:00:00+10:00"],
        name="Date",
    )
    frame = pd.DataFrame(
        {
            "Open": [25.39, 25.50],
            "High": [25.64, 25.62],
            "Low": [25.37, 25.27],
            "Close": [25.46, 25.31],
            "Adj Close": [19.53, 19.41],
            "Volume": [5_134_742, 5_698_793],
            "Dividends": [0.0, 0.0],
            "Stock Splits": [0.0, 0.0],
        },
        index=index,
    )
    security = Security(1, "WBC", "Westpac", "WBC.AX", "AUD")
    rows = history_rows(security, frame)
    assert len(rows) == 2
    assert rows[0][1] == date(2021, 9, 27)
    assert rows[0][5] == 25.46
    assert rows[0][6] == 19.53
    assert rows[0][7] == 5_134_742


def test_history_rows_skip_missing_or_nonpositive_close():
    index = pd.DatetimeIndex(
        ["2021-09-27", "2021-09-28", "2021-09-29"], name="Date"
    )
    frame = pd.DataFrame(
        {
            "Close": [10.0, float("nan"), 0.0],
            "High": [10.2, 9.0, 0.0],
            "Low": [9.8, 8.0, 0.0],
        },
        index=index,
    )
    security = Security(1, "ABC", "Example", "ABC.AX", "AUD")
    rows = history_rows(security, frame)
    assert len(rows) == 1
    assert rows[0][5] == 10.0


def test_optional_float_rejects_nan():
    assert optional_float(float("nan")) is None
    assert optional_float(3) == 3.0


def test_parse_asx_directory_csv():
    content = (
        '"ASX code","Company name","GICs industry group","Listing date",'
        '"Market Cap"\n'
        '"WBC","WESTPAC BANKING CORPORATION","Banks","18/07/1970",'
        "100000000000\n"
    )
    entries = parse_asx_directory_csv(content)
    assert entries == [
        {
            "exchange_code": "WBC",
            "issuer_name": "WESTPAC BANKING CORPORATION",
            "provider_symbol": "WBC.AX",
            "industry_group": "Banks",
            "listing_date": date(1970, 7, 18),
            "market_cap": 100_000_000_000,
        }
    ]
    missing_market_cap = content.replace("100000000000", "--")
    assert parse_asx_directory_csv(missing_market_cap)[0]["market_cap"] is None


def test_stale_first_selection_uses_source_before_limit():
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def execute(self, query, parameters):
            self.query = query
            self.parameters = parameters

        def fetchall(self):
            return [(1, "WBC", "Westpac", "WBC.AX", "AUD")]

    class Connection:
        def __init__(self):
            self.db_cursor = Cursor()

        def cursor(self):
            return self.db_cursor

    connection = Connection()
    securities = select_securities(
        connection,
        stale_first=True,
        limit=25,
    )
    assert securities == [Security(1, "WBC", "Westpac", "WBC.AX", "AUD")]
    assert "NULLS FIRST" in connection.db_cursor.query
    assert connection.db_cursor.parameters == [
        "yahoo",
        "yahoo_via_yfinance",
        25,
    ]
