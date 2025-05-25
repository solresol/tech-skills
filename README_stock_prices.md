# Stock Price Fetcher

This repository includes a small tool for retrieving the closing price of a
U.S. stock ticker for a specific date. The information is stored in a
`stock_prices` table so subsequent requests can be served from the database.

## Setup
1. Ensure a PostgreSQL database is available and a `db.conf` file describes how
   to connect to it (see other scripts in this repo for the format).
2. Install the Python dependencies for this project. `yfinance` is required for
   retrieving stock prices:
   ```bash
   pip install yfinance
   ```
3. Create the table by executing:
   ```bash
   psql -f stock_price_schema.sql
   ```

## Usage
Run the script with a ticker symbol and a date in `YYYY-MM-DD` format:
```bash
python get_stock_price.py AAPL 2024-05-10
```
The script will output the closing price and store it in the database.
If the record already exists, the stored value is printed without reaching out
to the network.
