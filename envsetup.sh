#!/bin/bash
set -e

sudo apt update
sudo apt install -y postgresql

# Ensure PostgreSQL is running (some systems don't start it automatically)
if ! pg_isready -q; then
    if command -v service >/dev/null 2>&1; then
        sudo service postgresql start
    elif command -v systemctl >/dev/null 2>&1; then
        sudo systemctl start postgresql
    fi
fi

uv run uvbootstrap.py

# Create database and user if they don't already exist
sudo -u postgres psql -c "CREATE USER techskills WITH PASSWORD 'techskills';" >/dev/null 2>&1 || true
sudo -u postgres psql -c "CREATE DATABASE techskills OWNER techskills;" >/dev/null 2>&1 || true

cat > db.conf <<EOC
[database]
user=techskills
password=techskills
hostname=localhost
port=5432
dbname=techskills

[minified]
user=techskills
password=techskills
hostname=localhost
port=5432
dbname=techskills_min

[edgar]
useragent="example@example.com"
EOC

wget -O techskills.sql.gz http://datadumps.ifost.org.au/tech-skills/techskills.sql.gz
gunzip -f techskills.sql.gz
psql -U techskills -d techskills -f techskills.sql
rm techskills.sql
