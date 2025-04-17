#!/usr/bin/env python

import os
import argparse
import urllib.parse
import pgconnect
from datetime import datetime
import jinja2
import shutil


def create_output_directory(output_dir):
    """Create output directory structure."""
    if os.path.exists(output_dir):
        # Don't delete existing directory, just make sure subdirectories exist
        os.makedirs(os.path.join(output_dir, "directors"), exist_ok=True)
        os.makedirs(os.path.join(output_dir, "css"), exist_ok=True)
        os.makedirs(os.path.join(output_dir, "js"), exist_ok=True)
    else:
        os.makedirs(output_dir)
        os.makedirs(os.path.join(output_dir, "directors"))
        os.makedirs(os.path.join(output_dir, "css"))
        os.makedirs(os.path.join(output_dir, "js"))


def encode_director_name(name):
    """Convert director name to URL-safe string."""
    # To-do. The real solution here is to collect all pairs of names
    # that have a high trigram overlap, together with everything we know
    # about them, and see if gpt-4o-mini thinks they are the same person
    # At the moment, we have the problem that if one person has two spellings
    # we only write a file out for one of them (and it's random which).

    # We don't handle Christopher O'Neill properly, because one spelling
    # uses ' and the other uses a non-ASCII symbol
    name = name.replace('"', '')
    name = name.replace("'", '')
    name = name.replace(',', '')
    name = name.replace('(', '')
    name = name.replace(')', '')
    # Make sure Claire Babineaux-Fontenot and Claire Baineaux- Fotenot are the same
    name = name.replace('- ', '-')
    # Make sure A. F. Sloan and A.F. Sloan are the same person
    name = name.replace('.', '. ')
    name = name.replace('.', '. ')
    old_name = None
    while old_name != name:
        old_name = name
        name = name.replace('  ', ' ')
    return urllib.parse.quote(name.lower().replace(" ", "-"))


def create_css(output_dir):
    """Create CSS file for styling."""
    css_content = """
    :root {
        --primary-color: #2c3e50;
        --secondary-color: #3498db;
        --accent-color: #e74c3c;
        --background-color: #f9f9f9;
        --text-color: #333;
        --light-gray: #ecf0f1;
        --dark-gray: #7f8c8d;
    }
    
    * {
        box-sizing: border-box;
        margin: 0;
        padding: 0;
    }
    
    body {
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        line-height: 1.6;
        color: var(--text-color);
        background-color: var(--background-color);
        max-width: 1200px;
        margin: 0 auto;
        padding: 20px;
    }
    
    header {
        background-color: var(--primary-color);
        color: white;
        padding: 20px;
        margin-bottom: 20px;
        border-radius: 5px;
    }
    
    header h1 {
        margin: 0;
    }
    
    header p {
        margin-top: 10px;
        color: var(--light-gray);
    }
    
    a {
        color: var(--secondary-color);
        text-decoration: none;
    }
    
    a:hover {
        text-decoration: underline;
        color: var(--accent-color);
    }
    
    .container {
        background-color: white;
        border-radius: 5px;
        box-shadow: 0 2px 5px rgba(0, 0, 0, 0.1);
        padding: 20px;
        margin-bottom: 20px;
    }
    
    table {
        width: 100%;
        border-collapse: collapse;
        margin: 20px 0;
    }
    
    th, td {
        padding: 12px 15px;
        text-align: left;
        border-bottom: 1px solid var(--light-gray);
    }
    
    th {
        background-color: var(--light-gray);
        font-weight: bold;
    }
    
    tr:hover {
        background-color: rgba(236, 240, 241, 0.5);
    }
    
    .director-list {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
        gap: 15px;
        margin-top: 20px;
    }
    
    .director-card {
        background-color: white;
        border-radius: 5px;
        padding: 15px;
        box-shadow: 0 2px 5px rgba(0, 0, 0, 0.1);
        transition: transform 0.3s ease;
    }
    
    .director-card:hover {
        transform: translateY(-5px);
        box-shadow: 0 5px 15px rgba(0, 0, 0, 0.1);
    }
    
    .company-section {
        margin-top: 30px;
        margin-bottom: 20px;
    }
    
    .company-section h2 {
        color: var(--primary-color);
        border-bottom: 2px solid var(--light-gray);
        padding-bottom: 10px;
        margin-bottom: 20px;
    }
    
    .footnote {
        margin-top: 30px;
        padding-top: 20px;
        border-top: 1px solid var(--light-gray);
        color: var(--dark-gray);
        font-size: 0.9em;
    }
    
    .search-container {
        margin-bottom: 20px;
    }
    
    #directorSearch {
        width: 100%;
        padding: 10px;
        border: 1px solid var(--light-gray);
        border-radius: 5px;
        font-size: 16px;
    }
    
    .back-link {
        display: inline-block;
        margin-bottom: 20px;
    }
    
    .pagination {
        display: flex;
        justify-content: center;
        margin-top: 20px;
    }
    
    .pagination button {
        background-color: var(--light-gray);
        border: none;
        padding: 8px 16px;
        margin: 0 5px;
        cursor: pointer;
        border-radius: 5px;
    }
    
    .pagination button:hover {
        background-color: var(--secondary-color);
        color: white;
    }
    
    .pagination button.active {
        background-color: var(--primary-color);
        color: white;
    }
    """
    
    with open(os.path.join(output_dir, "css", "style.css"), "w") as f:
        f.write(css_content)


def create_js(output_dir):
    """Create JavaScript file for interactivity."""
    js_content = """
    document.addEventListener('DOMContentLoaded', function() {
        // Search functionality for directors
        const searchInput = document.getElementById('directorSearch');
        if (searchInput) {
            searchInput.addEventListener('input', function() {
                const searchTerm = this.value.toLowerCase();
                const directorCards = document.querySelectorAll('.director-card');
                
                directorCards.forEach(card => {
                    const directorName = card.textContent.toLowerCase();
                    if (directorName.includes(searchTerm)) {
                        card.style.display = '';
                    } else {
                        card.style.display = 'none';
                    }
                });
            });
        }
        
        // Sort tables by date if they exist
        const tables = document.querySelectorAll('table');
        tables.forEach(table => {
            // Sort table rows by first column (date) in descending order
            const rows = Array.from(table.querySelectorAll('tbody tr'));
            
            rows.sort((a, b) => {
                const dateA = new Date(a.cells[0].textContent);
                const dateB = new Date(b.cells[0].textContent);
                return dateB - dateA; // Descending order (newest first)
            });
            
            // Re-append the sorted rows
            const tbody = table.querySelector('tbody');
            rows.forEach(row => tbody.appendChild(row));
        });
    });
    """
    
    with open(os.path.join(output_dir, "js", "script.js"), "w") as f:
        f.write(js_content)


def setup_jinja_environment():
    """Setup Jinja2 templates."""
    # Create Jinja2 templates
    index_template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Corporate Board Directors Database</title>
    <link rel="stylesheet" href="css/style.css">
</head>
<body>
    <header>
        <h1>Corporate Board Directors Database</h1>
        <p>Explore directors of U.S. listed companies</p>
    <p>{{percent_complete|round(2)}}% of {{doc_cache_size}} filings analysed</p>
    </header>
    
    <div class="container">
        <div class="search-container">
            <input type="text" id="directorSearch" placeholder="Search for a director...">
        </div>
        
        <div class="director-list">
            {% for director in directors %}
            <div class="director-card">
                <a href="directors/{{ director.url }}.html">{{ director.name }}</a>
            </div>
            {% endfor %}
        </div>
    </div>
    
    <div class="footnote">
        <p>Data sourced from SEC filings. Last updated: {{ last_updated }}</p>
    </div>
    
    <script src="js/script.js"></script>
</body>
</html>"""

    director_template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ director_name }} - Corporate Board Profile</title>
    <link rel="stylesheet" href="../css/style.css">
</head>
<body>
    <header>
        <h1>{{ director_name }}</h1>
        <p>Corporate Board Profile</p>
    </header>
    
    <a href="../index.html" class="back-link">← Back to All Directors</a>
    
    {% for company_name, mentions in companies.items() %}
    <div class="container company-section">
        <h2>{{ company_name }}</h2>
        <table>
            <thead>
                <tr>
                    <th>Filing Date</th>
                    <th>Source Excerpt</th>
                </tr>
            </thead>
            <tbody>
                {% for mention in mentions %}
                <tr>
                    <td><a href="{{ mention.document_storage_url }}" target="_blank">{{ mention.filingdate }}</a></td>
                    <td>{{ mention.source_excerpt }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    {% endfor %}
    
    <div class="footnote">
        <p>Data sourced from SEC filings. Last updated: {{ last_updated }}</p>
    </div>
    
    <script src="../js/script.js"></script>
</body>
</html>"""

    # Setup Jinja2 environment
    templates = {
        'index': jinja2.Template(index_template),
        'director': jinja2.Template(director_template)
    }
    
    return templates


def fetch_data(conn):
    """Fetch all required data from database."""
    cursor = conn.cursor()

    cursor.execute("select count(*) from html_doc_cache")
    row = cursor.fetchone()
    doc_cache_size = row[0]

    cursor.execute("select count(distinct accessionNumber) from director_extraction_raw")
    row = cursor.fetchone()
    accessions_processed = row[0]
    percent_complete = 100.0 * accessions_processed / doc_cache_size
    if percent_complete > 100:
        # There are some duplicate accessionNumbers
        percent_complete = 100.0
    
    
    # Main query to get all director mentions with company info
    query = """
    SELECT 
        director_name, 
        company_name, 
        filingdate, 
        source_excerpt, 
        document_storage_url 
    FROM 
        director_mentions 
        JOIN filings USING (cikcode, accessionnumber) 
        JOIN cik2name USING (cikcode) 
    ORDER BY 
        director_name, company_name, filingdate
    """
    cursor.execute(query)
    all_data = cursor.fetchall()
    
    # Query to get distinct directors for index page
    cursor.execute("SELECT DISTINCT director_name FROM director_mentions ORDER BY director_name")
    directors = cursor.fetchall()
    
    cursor.close()
    
    return doc_cache_size, percent_complete, all_data, directors


def process_data(all_data):
    """Process data into a format suitable for templates."""
    # Structure: {director_name: {company_name: [mention1, mention2, ...]}}
    director_profiles = {}
    
    for row in all_data:
        director_name, company_name, filingdate, source_excerpt, document_url = row
        
        if director_name not in director_profiles:
            director_profiles[director_name] = {}
            
        if company_name not in director_profiles[director_name]:
            director_profiles[director_name][company_name] = []
            
        director_profiles[director_name][company_name].append({
            'filingdate': filingdate,
            'source_excerpt': source_excerpt,
            'document_storage_url': document_url
        })
    
    return director_profiles


def generate_website(output_dir, conn):
    """Generate the website."""
    # Fetch data
    doc_cache_size, percent_complete, all_data, directors = fetch_data(conn)
    
    # Process data
    director_profiles = process_data(all_data)
    
    # Setup Jinja2 templates
    templates = setup_jinja_environment()
    
    # Current date for "last updated"
    last_updated = datetime.now().strftime("%Y-%m-%d")
    
    # Generate index page
    director_list = [
        {'name': director[0], 'url': encode_director_name(director[0])} 
        for director in directors
    ]
    
    with open(os.path.join(output_dir, "index.html"), "w") as f:
        f.write(templates['index'].render(
            directors=director_list,
            last_updated=last_updated,
            percent_complete=percent_complete,
            doc_cache_size=doc_cache_size
        ))
    
    # Generate director pages
    for director_name, companies in director_profiles.items():
        url_safe_name = encode_director_name(director_name)
        with open(os.path.join(output_dir, "directors", f"{url_safe_name}.html"), "w") as f:
            f.write(templates['director'].render(
                director_name=director_name,
                companies=companies,
                last_updated=last_updated
            ))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Generate a website for US corporate board directors")
    parser.add_argument("--database-config", default="db.conf", help="Parameters to connect to the database")
    parser.add_argument("--output-directory", default="./boards-website", help="Directory to output the generated website")
    args = parser.parse_args()
    
    # Connect to database
    conn = pgconnect.connect(args.database_config)
    
    # Setup directory structure
    create_output_directory(args.output_directory)
    
    # Create CSS and JS files
    create_css(args.output_directory)
    create_js(args.output_directory)
    
    # Generate website
    generate_website(args.output_directory, conn)
    
    # Close database connection
    conn.close()
