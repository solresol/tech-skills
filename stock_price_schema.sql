-- Table to store historical closing prices for U.S. stocks
CREATE TABLE IF NOT EXISTS stock_prices (
    ticker TEXT NOT NULL,
    price_date DATE NOT NULL,
    close_price NUMERIC,
    PRIMARY KEY (ticker, price_date)
);
