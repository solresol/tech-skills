-- Create a view that combines CIK, ticker, and company name information
CREATE OR REPLACE VIEW company_ticker_info AS
SELECT 
    c.cikcode,
    c.company_name,
    t.ticker
FROM 
    cik2name c
JOIN 
    cik_to_ticker t ON c.cikcode = t.cikcode;

-- Create a function to find a company by ticker
CREATE OR REPLACE FUNCTION get_company_by_ticker(ticker_symbol VARCHAR)
RETURNS TABLE (
    cikcode INT,
    company_name VARCHAR,
    ticker VARCHAR
) AS $$
BEGIN
    RETURN QUERY
    SELECT * FROM company_ticker_info
    WHERE UPPER(ticker) = UPPER(ticker_symbol);
END;
$$ LANGUAGE plpgsql;