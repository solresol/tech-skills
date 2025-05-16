-- Schema for storing director compensation, age, role, and committee information

-- Table for tracking extraction batches
CREATE TABLE IF NOT EXISTS director_extract_batches (
    id SERIAL PRIMARY KEY,
    openai_batch_id TEXT,
    when_sent TIMESTAMP,
    when_completed TIMESTAMP
);

-- Table for tracking which URLs have been processed
CREATE TABLE IF NOT EXISTS director_compensation (
    url TEXT PRIMARY KEY,
    batch_id INT REFERENCES director_extract_batches(id),
    processed BOOLEAN DEFAULT FALSE
);

-- Table for storing director information
CREATE TABLE IF NOT EXISTS director_details (
    id SERIAL PRIMARY KEY,
    url TEXT REFERENCES director_compensation(url),
    name TEXT NOT NULL,
    age INT,
    role TEXT,
    compensation INT,
    source_excerpt TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table for storing committee memberships
CREATE TABLE IF NOT EXISTS director_committees (
    id SERIAL PRIMARY KEY,
    director_id INT REFERENCES director_details(id),
    committee_name TEXT NOT NULL,
    UNIQUE(director_id, committee_name)
);

-- Create indexes for faster queries
CREATE INDEX IF NOT EXISTS idx_director_details_url ON director_details(url);
CREATE INDEX IF NOT EXISTS idx_director_details_name ON director_details(name);
CREATE INDEX IF NOT EXISTS idx_director_committees_director_id ON director_committees(director_id);
CREATE INDEX IF NOT EXISTS idx_director_committees_committee_name ON director_committees(committee_name);

-- Create a view to join director details with their committees
CREATE OR REPLACE VIEW director_full_details AS
SELECT 
    d.id,
    d.url,
    d.name,
    d.age,
    d.role,
    d.compensation,
    (SELECT array_agg(committee_name) FROM director_committees WHERE director_id = d.id) AS committees,
    d.source_excerpt
FROM 
    director_details d;