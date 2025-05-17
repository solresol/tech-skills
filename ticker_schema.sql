-- Schema for the CIK to ticker mapping

-- Create a new table for storing cikcode to ticker mappings
CREATE TABLE IF NOT EXISTS cik_to_ticker (
    cikcode INT NOT NULL,
    ticker VARCHAR NOT NULL,
    PRIMARY KEY (cikcode, ticker)
);

-- Create index for faster lookups by ticker
CREATE INDEX IF NOT EXISTS idx_cik_to_ticker_ticker ON cik_to_ticker(ticker);

-- Create index for faster lookups by cikcode
CREATE INDEX IF NOT EXISTS idx_cik_to_ticker_cikcode ON cik_to_ticker(cikcode);