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
    ('ACLEW', 'Healthcare'),
    ('ADZCF', 'Financial Services'),
    ('AEAEW', 'Financial Services'),
    ('AEFC', 'Financial Services'),
    ('AERGP', 'Industrials'),
    ('AFBL', 'Financial Services'),
    ('AFGB', 'Financial Services'),
    ('AFGC', 'Financial Services'),
    ('AFGD', 'Financial Services'),
    ('AFGE', 'Financial Services')
ON CONFLICT DO NOTHING;
