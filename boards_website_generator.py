#!/usr/bin/env python

import os
import argparse
import urllib.parse
import json
from datetime import datetime, timedelta
from math import ceil
import jinja2
import shutil
import networkx as nx
import pgconnect


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

    # Handle None value
    if name is None:
        return "unknown-director"
        
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
    return urllib.parse.quote_plus(name.lower())


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
        --tech-low: #cccccc;      /* Gray for non-tech */
        --tech-mid: #3498db;      /* Blue for medium tech */
        --tech-high: #2ecc71;     /* Green for high tech */
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

    nav {
        margin-top: 15px;
    }

    .nav-links {
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        margin-top: 10px;
    }

    .nav-links a {
        display: inline-block;
        background-color: var(--secondary-color);
        color: white;
        padding: 8px 14px;
        border-radius: 5px;
        font-weight: 600;
    }

    .nav-links a:hover {
        text-decoration: none;
        background-color: var(--accent-color);
        color: white;
    }

    /* Tech score color classes */
    .tech-score-0 { color: var(--tech-low); }
    .tech-score-10 { color: rgb(204, 204, 220); }
    .tech-score-20 { color: rgb(178, 190, 230); }
    .tech-score-30 { color: rgb(152, 175, 240); }
    .tech-score-40 { color: rgb(126, 161, 245); }
    .tech-score-50 { color: rgb(100, 146, 237); }
    .tech-score-60 { color: rgb(89, 156, 225); }
    .tech-score-70 { color: rgb(78, 166, 213); }
    .tech-score-80 { color: rgb(67, 177, 201); }
    .tech-score-90 { color: rgb(56, 187, 189); }
    .tech-score-100 { color: var(--tech-high); }
    
    .tech-score-badge {
        display: inline-block;
        padding: 3px 8px;
        border-radius: 12px;
        background-color: var(--light-gray);
        color: var(--text-color);
        font-size: 0.8em;
        margin-left: 8px;
    }
    
    .tech-evidence {
        margin-top: 20px;
        background-color: rgba(46, 204, 113, 0.1);
        border-left: 3px solid var(--tech-high);
        padding: 15px;
        border-radius: 4px;
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

    .metrics-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 20px;
        margin-top: 20px;
    }

    .metric-card {
        background-color: var(--light-gray);
        border-radius: 8px;
        padding: 20px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
    }

    .metric-card h3 {
        margin-bottom: 10px;
        font-size: 1.1em;
        color: var(--primary-color);
    }

    .metric-card p {
        font-size: 1.4em;
        font-weight: bold;
    }

    .metric-card span {
        display: block;
        margin-top: 6px;
        font-size: 0.9em;
        color: var(--dark-gray);
    }

    .chart-container {
        margin-top: 20px;
    }

    .chart-container canvas {
        width: 100%;
        max-height: 420px;
    }

    .projection-note {
        margin-top: 15px;
        color: var(--dark-gray);
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
    <title>Database of Software Skills in Corporate Board Directors</title>
    <link rel="stylesheet" href="css/style.css">
</head>
<body>
    <header>
        <h1>Database of Software Skills in Corporate Board Directors</h1>
        <p>Explore directors of U.S. listed companies</p>
        <p>{{percent_complete|round(2)}}% of {{doc_cache_size}} filings analysed</p>
        <p><strong>{{software_skills_percentage|round(1)}}%</strong> of board directors have software skills</p>
        <nav>
            <div class="nav-links">
                <a href="progress.html">Processing Progress</a>
            </div>
        </nav>
    </header>

    <div class="purpose">
    <p>
    <a href="https://a16z.com/why-software-is-eating-the-world/">Software is eating the world</a>. The future of business is bots-supervising-bots to do the white collar work, with a small dash of human oversight.
    </p>
    <p>
    A lot has to happen to get us from here to there safely. We need wise and knowledgeable leaders who understand how AI bots work at a deep level in order to guide us on this path. <a href="https://en.wikipedia.org/wiki/AI_alignment">AI Alignment</a> is not something that you can do if you only have a high-level understanding. So let's ask how many directors seem to have the right background that they would be able to review plans to use AI.
    </p>
    <p>
    Incidentally, I <a href="https://upskill.industrial-linguistics.com/">run workshops</a> for senior managers on these sorts of topics.
    </p>
    </div>
    
    <div class="container">
        <div class="search-container">
            <input type="text" id="directorSearch" placeholder="Search for a director...">
        </div>
        
        <div class="director-list">
            {% for director in directors %}
            <div class="director-card">
                {% set tech_score = director.tech_score|int %}
                {% set tech_class = "tech-score-" ~ (tech_score // 10 * 10) %}
                <a href="directors/{{ director.url }}.html" class="{{ tech_class }}">
                    {{ director.name }}
                    <span class="tech-score-badge">{{ tech_score }}</span>
                </a>
            </div>
            {% endfor %}
        </div>
    </div>
    
    <div class="container">
        <h2>About Tech Score</h2>
        <p>The Tech Score (0-100) indicates how often a director is described in terms of their software/technology skills or background. 
        Higher scores mean stronger evidence of technology expertise.</p>
        <p>Color intensity reflects the score: gray (0) → blue (50) → green (100).</p>
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
        <p>Tech Score: <span class="tech-score-{{ tech_score_class }}">{{ tech_score }}</span>/100</p>
    </header>
    
    <a href="../index.html" class="back-link">← Back to All Directors</a>
    
    {% if tech_mentions and tech_mentions|length > 0 %}
    <div class="container company-section tech-evidence">
        <h2>Software Technology Evidence</h2>
        <p>{{ tech_mentions|length }} mention(s) identify {{ director_name }} as having software/technology expertise.</p>
        <table>
            <thead>
                <tr>
                    <th>Company</th>
                    <th>Filing Date</th>
                    <th>Evidence</th>
                    <th>Reason</th>
                </tr>
            </thead>
            <tbody>
                {% for mention in tech_mentions %}
                <tr>
                    <td>{{ mention.company_name }}</td>
                    <td><a href="{{ mention.document_storage_url }}" target="_blank">{{ mention.filingdate }}</a></td>
                    <td>{{ mention.source_excerpt }}</td>
                    <td>{{ mention.reason }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    {% endif %}
    
    {% for company_name, mentions in companies.items() if company_name != 'tech_mentions' %}
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

    progress_template = """<!DOCTYPE html>
<html lang=\"en\">
<head>
    <meta charset=\"UTF-8\">
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
    <title>Processing Progress</title>
    <link rel=\"stylesheet\" href=\"css/style.css\">
    <script src=\"https://cdn.jsdelivr.net/npm/chart.js\"></script>
</head>
<body>
    <header>
        <h1>Processing Progress</h1>
        <p>Tracking extraction throughput and projection</p>
        <nav>
            <div class=\"nav-links\">
                <a href=\"index.html\">← Back to Directory</a>
            </div>
        </nav>
    </header>

    <div class=\"container\">
        <h2>Summary</h2>
        <div class=\"metrics-grid\">
            <div class=\"metric-card\">
                <h3>Filings Processed</h3>
                <p>{{ '{:,}'.format(accessions_processed) }}</p>
                <span>of {{ '{:,}'.format(doc_cache_size) }} total</span>
            </div>
            <div class=\"metric-card\">
                <h3>Remaining Filings</h3>
                <p>{{ '{:,}'.format(remaining_filings) }}</p>
                <span>left to review</span>
            </div>
            <div class=\"metric-card\">
                <h3>Completion</h3>
                <p>{{ percent_complete|round(2) }}%</p>
                <span>last updated {{ last_updated }}</span>
            </div>
            <div class=\"metric-card\">
                <h3>7-Day Average</h3>
                {% if average_daily_rate is not none %}
                <p>{{ average_daily_rate|round(1) }}</p>
                <span>filings per day</span>
                {% else %}
                <p>—</p>
                <span>Not enough data yet</span>
                {% endif %}
            </div>
        </div>

        <div class=\"projection-note\">
            {% if projected_completion_date %}
            <p>
                At the recent pace (~{{ average_daily_rate|round(1) }} filings/day), projected completion is
                <strong>{{ projected_completion_date }}</strong>
                (about {{ remaining_days }} day{% if remaining_days != 1 %}s{% endif %} remaining).
            </p>
            {% else %}
            <p>Not enough recent data to project a completion date.</p>
            {% endif %}
        </div>

        {% if daily_labels %}
        <div class=\"chart-container\">
            <canvas id=\"dailyChart\"></canvas>
        </div>
        {% else %}
        <p class=\"projection-note\">No batch activity recorded yet.</p>
        {% endif %}
    </div>

    <div class=\"container\">
        <h2>Daily Filings Completed</h2>
        {% if daily_progress_table %}
        <table>
            <thead>
                <tr>
                    <th>Date</th>
                    <th>Filings Completed</th>
                </tr>
            </thead>
            <tbody>
                {% for row in daily_progress_table %}
                <tr>
                    <td>{{ row.day }}</td>
                    <td>{{ '{:,}'.format(row.filings_completed) }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% else %}
        <p>No daily completion data available.</p>
        {% endif %}
    </div>

    <div class=\"footnote\">
        <p>Data sourced from SEC filings. Last updated: {{ last_updated }}</p>
    </div>

    <script>
    document.addEventListener('DOMContentLoaded', function() {
        const labels = {{ daily_labels_json | safe }};
        const dataPoints = {{ daily_counts_json | safe }};
        if (labels.length > 0 && dataPoints.length > 0) {
            const canvas = document.getElementById('dailyChart');
            if (canvas) {
                const ctx = canvas.getContext('2d');
                new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: labels,
                        datasets: [{
                            label: 'Filings completed per day',
                            data: dataPoints,
                            fill: false,
                            borderColor: '#3498db',
                            backgroundColor: 'rgba(52, 152, 219, 0.2)',
                            tension: 0.2,
                            pointRadius: 3
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        scales: {
                            y: {
                                beginAtZero: true,
                                ticks: {
                                    precision: 0
                                }
                            }
                        }
                    }
                });
            }
        } else {
            const chartElement = document.getElementById('dailyChart');
            if (chartElement && chartElement.parentElement) {
                chartElement.parentElement.style.display = 'none';
            }
        }
    });
    </script>
    <script src=\"js/script.js\"></script>
</body>
</html>"""

    # Setup Jinja2 environment
    templates = {
        'index': jinja2.Template(index_template),
        'director': jinja2.Template(director_template),
        'progress': jinja2.Template(progress_template)
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
    
    # Query to get percentage of directors with software background
    cursor.execute("select avg(cast(software_background as int))*100.0 from director_mentions")
    row = cursor.fetchone()
    software_skills_percentage = row[0]
    
    # Main query to get all director mentions with company info and tech background
    query = """
    SELECT 
        director_name, 
        company_name, 
        filingdate, 
        source_excerpt, 
        document_storage_url,
        software_background,
        reason
    FROM 
        director_mentions 
        JOIN filings USING (cikcode, accessionnumber) 
        JOIN cik2name USING (cikcode) 
    ORDER BY 
        director_name, company_name, filingdate
    """
    cursor.execute(query)
    all_data = cursor.fetchall()
    
    # Query to get distinct directors with their tech scores for index page
    tech_score_query = """
    SELECT 
        director_name,
        ROUND(100.0 * SUM(CASE WHEN software_background THEN 1 ELSE 0 END) / COUNT(*)) AS tech_score
    FROM 
        director_mentions
    GROUP BY 
        director_name
    ORDER BY 
        director_name
    """
    cursor.execute(tech_score_query)
    directors = cursor.fetchall()

    daily_progress_query = """
    WITH snapshots AS (
        SELECT
            batch_id,
            when_checked::date AS day,
            MAX(number_completed) AS completed
        FROM batchprogress
        GROUP BY batch_id, day
    ),
    daily AS (
        SELECT
            batch_id,
            day,
            completed - LAG(completed, 1, 0) OVER (
                PARTITION BY batch_id
                ORDER BY day
            ) AS processed
        FROM snapshots
    )
    SELECT
        day,
        SUM(GREATEST(processed, 0)) AS filings_completed
    FROM daily
    GROUP BY day
    ORDER BY day
    """
    cursor.execute(daily_progress_query)
    daily_progress = cursor.fetchall()

    cursor.close()

    return (
        doc_cache_size,
        percent_complete,
        all_data,
        directors,
        software_skills_percentage,
        accessions_processed,
        daily_progress,
    )


def process_data(all_data):
    """Process data into a format suitable for templates."""
    # Structure: {director_name: {company_name: [mention1, mention2, ...]}}
    director_profiles = {}
    
    for row in all_data:
        director_name, company_name, filingdate, source_excerpt, document_url, software_background, reason = row
        
        if director_name not in director_profiles:
            director_profiles[director_name] = {}
            director_profiles[director_name]['tech_mentions'] = []
            
        if company_name not in director_profiles[director_name]:
            director_profiles[director_name][company_name] = []
            
        # Add mention to company list
        director_profiles[director_name][company_name].append({
            'filingdate': filingdate,
            'source_excerpt': source_excerpt,
            'document_storage_url': document_url,
            'software_background': software_background,
            'reason': reason
        })
        
        # If this is a tech mention, add to tech_mentions for evidence
        if software_background:
            director_profiles[director_name]['tech_mentions'].append({
                'company_name': company_name,
                'filingdate': filingdate,
                'source_excerpt': source_excerpt,
                'document_storage_url': document_url,
                'reason': reason
            })
    
    return director_profiles


def generate_network_visualization(output_dir, conn):
    """Create a force-directed network visualisation dataset and page."""
    cursor = conn.cursor()

    cursor.execute("SELECT cikcode, company_name FROM cik2name")
    name_lookup = dict(cursor.fetchall())

    cursor.execute(
        """
        SELECT c1.cikcode, c2.cikcode, COUNT(*)
        FROM company_directorships c1
        JOIN company_directorships c2
          ON c1.director_name = c2.director_name
         AND c1.cikcode < c2.cikcode
        GROUP BY c1.cikcode, c2.cikcode
        """
    )
    edges = cursor.fetchall()
    cursor.close()

    G = nx.Graph()

    for cik, name in name_lookup.items():
        G.add_node(cik, name=name)
    for c1, c2, weight in edges:
        G.add_edge(c1, c2, weight=weight)

    for component in nx.connected_components(G):
        sub = G.subgraph(component)
        try:
            centrality = nx.eigenvector_centrality(sub, max_iter=1000)
        except nx.PowerIterationFailedConvergence:
            centrality = nx.eigenvector_centrality_numpy(sub)
        for node, score in centrality.items():
            G.nodes[node]["centrality"] = score

    data = {
        "nodes": [
            {
                "id": cik,
                "name": G.nodes[cik]["name"],
                "centrality": G.nodes[cik].get("centrality", 0.0),
            }
            for cik in G.nodes
        ],
        "links": [
            {"source": u, "target": v, "weight": d["weight"]}
            for u, v, d in G.edges(data=True)
        ],
    }

    with open(os.path.join(output_dir, "network_data.json"), "w") as f:
        json.dump(data, f)

    html = """<!DOCTYPE html>
<html lang=\"en\">
<head>
    <meta charset=\"UTF-8\">
    <title>Company Director Network</title>
    <script src=\"https://d3js.org/d3.v7.min.js\"></script>
    <link rel=\"stylesheet\" href=\"css/style.css\">
</head>
<body>
    <h1>Company Director Network</h1>
    <div id=\"network\"></div>
    <script>
    fetch('network_data.json').then(r => r.json()).then(data => {
        const width = 960, height = 600;
        const svg = d3.select('#network').append('svg')
            .attr('width', width)
            .attr('height', height);

        const maxCentrality = d3.max(data.nodes, d => d.centrality);
        const sizeScale = d3.scaleLinear()
            .domain([0, maxCentrality])
            .range([5, 25]);
        const colorScale = d3.scaleSequential(d3.interpolateBlues)
            .domain([0, maxCentrality]);

        const simulation = d3.forceSimulation(data.nodes)
            .force('link', d3.forceLink(data.links).id(d => d.id).distance(100))
            .force('charge', d3.forceManyBody().strength(-50))
            .force('center', d3.forceCenter(width / 2, height / 2));

        const link = svg.append('g').selectAll('line')
            .data(data.links)
            .enter().append('line')
            .attr('stroke', '#999')
            .attr('stroke-opacity', 0.6);

        const node = svg.append('g').selectAll('circle')
            .data(data.nodes)
            .enter().append('circle')
            .attr('r', d => sizeScale(d.centrality))
            .attr('fill', d => colorScale(d.centrality))
            .call(d3.drag()
                .on('start', dragstarted)
                .on('drag', dragged)
                .on('end', dragended));

        const labels = svg.append('g').selectAll('text')
            .data(data.nodes)
            .enter().append('text')
            .text(d => d.name)
            .attr('font-size', 10)
            .attr('dx', 8)
            .attr('dy', 3);

        node.append('title').text(d => d.name);

        simulation.on('tick', () => {
            link
                .attr('x1', d => d.source.x)
                .attr('y1', d => d.source.y)
                .attr('x2', d => d.target.x)
                .attr('y2', d => d.target.y);

            node
                .attr('cx', d => d.x)
                .attr('cy', d => d.y);

            labels
                .attr('x', d => d.x)
                .attr('y', d => d.y);
        });

        function dragstarted(event, d) {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
        }
        function dragged(event, d) {
            d.fx = event.x;
            d.fy = event.y;
        }
        function dragended(event, d) {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
        }
    });
    </script>
</body>
</html>
"""

    with open(os.path.join(output_dir, "network.html"), "w") as f:
        f.write(html)



def generate_website(output_dir, conn):
    """Generate the website."""
    # Fetch data
    (
        doc_cache_size,
        percent_complete,
        all_data,
        directors,
        software_skills_percentage,
        accessions_processed,
        daily_progress,
    ) = fetch_data(conn)

    # Process data
    director_profiles = process_data(all_data)

    # Create a dictionary to map director names to tech scores
    tech_scores = {director[0]: director[1] for director in directors}

    # Prepare progress metrics
    daily_progress_records = [
        {
            'day': record[0],
            'filings_completed': record[1] if record[1] is not None else 0,
        }
        for record in daily_progress
        if record[0] is not None
    ]

    daily_progress_records.sort(key=lambda entry: entry['day'])

    daily_labels = [entry['day'].strftime("%Y-%m-%d") for entry in daily_progress_records]
    daily_counts = [int(entry['filings_completed']) for entry in daily_progress_records]

    recent_records = [entry for entry in daily_progress_records if entry['filings_completed'] is not None]
    recent_window = recent_records[-7:]
    average_daily_rate = None
    if recent_window:
        average_daily_rate = sum(entry['filings_completed'] for entry in recent_window) / len(recent_window)

    remaining_filings = max(doc_cache_size - accessions_processed, 0)
    projected_completion_date = None
    remaining_days = None
    if average_daily_rate and average_daily_rate > 0:
        remaining_days = ceil(remaining_filings / average_daily_rate) if remaining_filings > 0 else 0
        projected_completion_date = (datetime.now().date() + timedelta(days=remaining_days)).isoformat()

    daily_progress_table = [
        {
            'day': entry['day'].strftime("%Y-%m-%d"),
            'filings_completed': int(entry['filings_completed']),
        }
        for entry in sorted(daily_progress_records, key=lambda item: item['day'], reverse=True)
    ]

    # Setup Jinja2 templates
    templates = setup_jinja_environment()

    # Current date for "last updated"
    last_updated = datetime.now().strftime("%Y-%m-%d")
    
    # Generate index page with tech scores
    director_list = [
        {
            'name': director[0], 
            'url': encode_director_name(director[0]),
            'tech_score': director[1]
        } 
        for director in directors
    ]
    
    with open(os.path.join(output_dir, "index.html"), "w") as f:
        f.write(templates['index'].render(
            directors=director_list,
            last_updated=last_updated,
            percent_complete=percent_complete,
            doc_cache_size=doc_cache_size,
            software_skills_percentage=software_skills_percentage
        ))

    with open(os.path.join(output_dir, "progress.html"), "w") as f:
        f.write(templates['progress'].render(
            accessions_processed=accessions_processed,
            doc_cache_size=doc_cache_size,
            remaining_filings=remaining_filings,
            percent_complete=percent_complete,
            last_updated=last_updated,
            average_daily_rate=average_daily_rate,
            projected_completion_date=projected_completion_date,
            remaining_days=remaining_days,
            daily_progress_table=daily_progress_table,
            daily_labels=daily_labels,
            daily_labels_json=json.dumps(daily_labels),
            daily_counts_json=json.dumps(daily_counts),
        ))

    # Generate director pages with tech evidence
    for director_name, companies in director_profiles.items():
        url_safe_name = encode_director_name(director_name)
        tech_score = tech_scores.get(director_name, 0)
        tech_score_class = (tech_score // 10) * 10  # Round down to nearest 10
        
        # Get tech mentions for this director
        tech_mentions = companies.get('tech_mentions', [])
        
        with open(os.path.join(output_dir, "directors", f"{url_safe_name}.html"), "w") as f:
            f.write(templates['director'].render(
                director_name=director_name,
                companies=companies,
                tech_score=tech_score,
                tech_score_class=tech_score_class,
                tech_mentions=tech_mentions,
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
    generate_network_visualization(args.output_directory, conn)
    
    # Close database connection
    conn.close()
