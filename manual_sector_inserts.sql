-- Insert known sectors for tickers with previously missing information
INSERT INTO ticker_sector (ticker, sector) VALUES
    ('AAAU', 'Financial Services'),
    ('AACT-WT', 'Financial Services'),
    ('AAGO', 'Financial Services'),
    ('AAM-WT', 'Financial Services'),
    ('AAS', 'Financial Services'),
    ('ABLLL', 'Financial Services'),
    ('ABLLW', 'Financial Services'),
    ('ACHR-WT', 'Industrials'),
    ('ACLEW', 'Healthcare')
ON CONFLICT DO NOTHING;
