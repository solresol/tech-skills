-- Add gender column to director_details table
ALTER TABLE director_details ADD COLUMN gender TEXT;

-- Drop and recreate the director_full_details view to include gender
DROP VIEW IF EXISTS director_full_details;
CREATE VIEW director_full_details AS
SELECT 
    d.id,
    d.url,
    d.name,
    d.age,
    d.role,
    d.compensation,
    d.gender,
    (SELECT array_agg(committee_name) FROM director_committees WHERE director_id = d.id) AS committees,
    d.source_excerpt
FROM 
    director_details d;

-- Drop and recreate the director_compensation_summary view to include gender
DROP VIEW IF EXISTS director_compensation_summary;
CREATE VIEW director_compensation_summary AS
SELECT 
    f.cikcode,
    f.accessionnumber,
    f.filingdate,
    dd.name,
    dd.age,
    dd.role,
    dd.compensation,
    dd.gender,
    (SELECT array_agg(committee_name) FROM director_committees WHERE director_id = dd.id) AS committees
FROM 
    director_details dd
JOIN 
    director_compensation dc ON dd.url = dc.url
JOIN 
    filings f ON dc.url = f.document_storage_url
WHERE 
    dc.processed = TRUE
ORDER BY 
    f.accessionnumber, dd.name;