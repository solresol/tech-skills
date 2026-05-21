#!/usr/bin/env python3
"""Generate reduced network pages for the board-director website."""

from __future__ import annotations

import csv
import itertools
import json
import math
import os
import re
from collections import defaultdict

import networkx as nx


NETWORK_PAGE_LINKS = [
    {
        "href": "network-all.html",
        "title": "All Shared-Director Links",
        "description": "The full non-isolate company graph. This keeps the original view but removes companies with no shared-director edge.",
    },
    {
        "href": "network-strong-2.html",
        "title": "Strong Ties: 2+ Shared Directors",
        "description": "Companies connected only when at least two directors appear on both boards.",
    },
    {
        "href": "network-strong-3.html",
        "title": "Strong Ties: 3+ Shared Directors",
        "description": "A stricter version that breaks the giant graph into smaller, more interpretable islands.",
    },
    {
        "href": "network-communities.html",
        "title": "Community Islands",
        "description": "Louvain communities inside the giant component, shown as capped islands of central companies.",
    },
    {
        "href": "network-fund-families.html",
        "title": "Fund-Family Clusters",
        "description": "Dense closed-end fund families that otherwise dominate the shared-director graph.",
    },
    {
        "href": "network-umap-giant.html",
        "title": "UMAP of Giant Island",
        "description": "A shortest-path UMAP layout of the largest connected component.",
    },
    {
        "href": "network-centrality-price.html",
        "title": "Centrality and Price",
        "description": "Exploratory correlations between graph centrality features and later share-price movement.",
    },
]

LANDING_NETWORK_PAGE_LINKS = [
    link
    for link in NETWORK_PAGE_LINKS
    if link["href"]
    in {
        "network-strong-3.html",
        "network-communities.html",
        "network-fund-families.html",
        "network-umap-giant.html",
        "network-centrality-price.html",
    }
]


FUND_FAMILY_PATTERNS = [
    ("BlackRock", re.compile(r"blackrock", re.I)),
    ("Nuveen", re.compile(r"nuveen", re.I)),
    ("PIMCO", re.compile(r"pimco", re.I)),
    ("Western Asset", re.compile(r"western asset|lmp ", re.I)),
    ("Eaton Vance", re.compile(r"eaton vance", re.I)),
    ("Invesco", re.compile(r"invesco", re.I)),
    ("MFS", re.compile(r"\bmfs\b", re.I)),
    ("Templeton/Pioneer", re.compile(r"templeton|pioneer", re.I)),
]


def generate_network_pages(output_dir, conn):
    """Generate graph-reduction pages and supporting JSON/CSV files."""

    graph = fetch_company_graph(conn)
    nonisolated_graph = strip_isolates(graph)
    add_component_metrics(nonisolated_graph)

    write_network_index(output_dir, graph, nonisolated_graph)

    write_graph_page(
        output_dir,
        "network-all.html",
        "All Shared-Director Links",
        "Every company with at least one shared-director edge.",
        "network_all_data.json",
        graph_to_d3_data(
            nonisolated_graph,
            "force",
            "component",
            note="Isolates are omitted from this display.",
        ),
        component_summary(nonisolated_graph, limit=12),
    )

    for threshold in (2, 3):
        strong_graph = threshold_graph(graph, threshold)
        add_component_metrics(strong_graph)
        write_graph_page(
            output_dir,
            f"network-strong-{threshold}.html",
            f"Strong Ties: {threshold}+ Shared Directors",
            f"Edges are kept only when companies share at least {threshold} directors.",
            f"network_strong_{threshold}_data.json",
            graph_to_d3_data(strong_graph, "force", "component"),
            component_summary(strong_graph, limit=15),
        )

    community_graph, community_rows = community_island_graph(graph)
    add_component_metrics(community_graph)
    write_graph_page(
        output_dir,
        "network-communities.html",
        "Community Islands",
        "Top Louvain communities inside the giant component, capped to the most central companies in each community.",
        "network_communities_data.json",
        graph_to_d3_data(community_graph, "force", "community"),
        community_rows,
        table_title="Shown Communities",
    )

    fund_graph, fund_rows = fund_family_graph(graph)
    add_component_metrics(fund_graph)
    write_graph_page(
        output_dir,
        "network-fund-families.html",
        "Fund-Family Clusters",
        "A targeted view of fund-family cliques that otherwise dominate the dense part of the graph.",
        "network_fund_families_data.json",
        graph_to_d3_data(fund_graph, "force", "family"),
        fund_rows,
        table_title="Fund Families",
    )

    _, umap_data, umap_rows = umap_giant_component(graph)
    write_graph_page(
        output_dir,
        "network-umap-giant.html",
        "UMAP of Giant Island",
        "UMAP coordinates computed from all-pairs shortest-path distances inside the largest connected component.",
        "network_umap_giant_data.json",
        umap_data,
        umap_rows,
        table_title="Largest-Component Summary",
    )

    write_centrality_price_analysis(output_dir, conn, graph)


def fetch_company_graph(conn):
    """Return a weighted company graph where edges count shared directors."""

    cursor = conn.cursor()
    cursor.execute("SELECT cikcode, company_name FROM cik2name")
    names = dict(cursor.fetchall())

    cursor.execute(
        """
        SELECT c.cikcode, MIN(t.ticker) AS ticker, MIN(s.sector) AS sector
          FROM cik2name c
          LEFT JOIN cik_to_ticker t ON c.cikcode = t.cikcode
          LEFT JOIN ticker_sector s ON t.ticker = s.ticker
         GROUP BY c.cikcode
        """
    )
    ticker_rows = {row[0]: {"ticker": row[1], "sector": row[2]} for row in cursor.fetchall()}

    cursor.execute(
        """
        WITH cd AS (
            SELECT DISTINCT cikcode, director_name
              FROM company_directorships
             WHERE director_name IS NOT NULL
        )
        SELECT c1.cikcode, c2.cikcode, COUNT(*) AS shared_directors
          FROM cd c1
          JOIN cd c2
            ON c1.director_name = c2.director_name
           AND c1.cikcode < c2.cikcode
         GROUP BY c1.cikcode, c2.cikcode
        """
    )
    edges = cursor.fetchall()
    cursor.close()

    graph = nx.Graph()
    for cik, name in names.items():
        attrs = ticker_rows.get(cik, {})
        family = classify_fund_family(name)
        graph.add_node(
            cik,
            name=name or str(cik),
            ticker=attrs.get("ticker"),
            sector=attrs.get("sector") or "Unknown",
            family=family,
        )
    for c1, c2, weight in edges:
        graph.add_edge(c1, c2, weight=int(weight))
    return graph


def strip_isolates(graph):
    return graph.subgraph([node for node, degree in graph.degree() if degree > 0]).copy()


def threshold_graph(graph, min_weight):
    selected_edges = [
        (u, v, data)
        for u, v, data in graph.edges(data=True)
        if data.get("weight", 1) >= min_weight
    ]
    nodes = set()
    for u, v, _ in selected_edges:
        nodes.add(u)
        nodes.add(v)
    reduced = nx.Graph()
    reduced.add_nodes_from((node, graph.nodes[node]) for node in nodes)
    reduced.add_edges_from(selected_edges)
    return reduced


def add_component_metrics(graph):
    if graph.number_of_nodes() == 0:
        return

    components = sorted(nx.connected_components(graph), key=len, reverse=True)
    for component_index, component in enumerate(components, start=1):
        subgraph = graph.subgraph(component)
        if subgraph.number_of_edges() > 0:
            try:
                eigenvector = nx.eigenvector_centrality(
                    subgraph, weight="weight", max_iter=1000
                )
            except nx.PowerIterationFailedConvergence:
                eigenvector = {node: 0.0 for node in subgraph.nodes}
            pagerank = nx.pagerank(subgraph, weight="weight")
        else:
            eigenvector = {node: 0.0 for node in subgraph.nodes}
            pagerank = {node: 0.0 for node in subgraph.nodes}

        for node in component:
            graph.nodes[node]["component"] = component_index
            graph.nodes[node]["component_size"] = len(component)
            graph.nodes[node]["degree"] = graph.degree(node)
            graph.nodes[node]["weighted_degree"] = graph.degree(node, weight="weight")
            graph.nodes[node]["centrality"] = eigenvector.get(node, 0.0)
            graph.nodes[node]["pagerank"] = pagerank.get(node, 0.0)


def community_island_graph(graph, limit=12, max_nodes_per_community=60):
    nonisolated = strip_isolates(graph)
    if nonisolated.number_of_nodes() == 0:
        return nx.Graph(), []

    giant_nodes = max(nx.connected_components(nonisolated), key=len)
    giant = nonisolated.subgraph(giant_nodes).copy()
    communities = sorted(
        nx.community.louvain_communities(
            giant, weight=None, resolution=2.0, seed=42
        ),
        key=len,
        reverse=True,
    )

    selected_nodes = set()
    rows = []
    for index, community in enumerate(communities[:limit], start=1):
        ranked_nodes = sorted(
            community,
            key=lambda node: giant.degree(node, weight="weight"),
            reverse=True,
        )
        shown_nodes = ranked_nodes[:max_nodes_per_community]
        selected_nodes.update(shown_nodes)
        for node in shown_nodes:
            giant.nodes[node]["community"] = f"Community {index}"
        hub_names = [giant.nodes[node]["name"] for node in ranked_nodes[:5]]
        rows.append(
            {
                "Community": f"Community {index}",
                "Original size": len(community),
                "Nodes shown": len(shown_nodes),
                "Top hubs": "; ".join(hub_names),
            }
        )

    reduced = giant.subgraph(selected_nodes).copy()
    for node in reduced.nodes:
        reduced.nodes[node]["community"] = giant.nodes[node].get("community", "Other")
    return reduced, rows


def classify_fund_family(name):
    if not name:
        return None
    for family, pattern in FUND_FAMILY_PATTERNS:
        if pattern.search(name):
            return family
    return None


def fund_family_graph(graph):
    selected_nodes = {
        node
        for node, attrs in graph.nodes(data=True)
        if attrs.get("family") is not None and graph.degree(node) > 0
    }
    reduced = graph.subgraph(selected_nodes).copy()

    rows = []
    for family, _ in FUND_FAMILY_PATTERNS:
        family_nodes = [
            node for node, attrs in reduced.nodes(data=True) if attrs.get("family") == family
        ]
        if not family_nodes:
            continue
        subgraph = reduced.subgraph(family_nodes)
        hub_names = [
            reduced.nodes[node]["name"]
            for node, _ in sorted(
                subgraph.degree(weight="weight"), key=lambda item: item[1], reverse=True
            )[:5]
        ]
        rows.append(
            {
                "Family": family,
                "Companies": len(family_nodes),
                "Internal edges": subgraph.number_of_edges(),
                "Top hubs": "; ".join(hub_names),
            }
        )

    return reduced, rows


def umap_giant_component(graph):
    nonisolated = strip_isolates(graph)
    if nonisolated.number_of_nodes() == 0:
        return nx.Graph(), empty_d3_data("fixed", "sector"), []

    giant_nodes = max(nx.connected_components(nonisolated), key=len)
    giant = nonisolated.subgraph(giant_nodes).copy()
    add_component_metrics(giant)

    nodes = sorted(giant.nodes)
    positions = shortest_path_umap_positions(giant, nodes)
    for node, coords in positions.items():
        giant.nodes[node]["x"] = coords[0]
        giant.nodes[node]["y"] = coords[1]

    strong_links = [
        (u, v, data)
        for u, v, data in giant.edges(data=True)
        if data.get("weight", 1) >= 2
    ]
    display_graph = nx.Graph()
    display_graph.add_nodes_from((node, giant.nodes[node]) for node in giant.nodes)
    display_graph.add_edges_from(strong_links)

    rows = [
        {
            "Measure": "Companies",
            "Value": f"{giant.number_of_nodes():,}",
        },
        {
            "Measure": "All shared-director edges",
            "Value": f"{giant.number_of_edges():,}",
        },
        {
            "Measure": "Displayed edges",
            "Value": f"{len(strong_links):,} edges with 2+ shared directors",
        },
        {
            "Measure": "Average shortest path",
            "Value": f"{nx.average_shortest_path_length(giant):.2f}",
        },
        {
            "Measure": "Diameter",
            "Value": f"{nx.diameter(giant):,}",
        },
    ]
    return giant, graph_to_d3_data(display_graph, "fixed", "sector"), rows


def shortest_path_umap_positions(graph, nodes):
    import numpy as np
    import umap

    index = {node: position for position, node in enumerate(nodes)}
    distances = np.zeros((len(nodes), len(nodes)), dtype=np.float32)
    for source, lengths in nx.all_pairs_shortest_path_length(graph):
        row = index[source]
        for target, distance in lengths.items():
            distances[row, index[target]] = distance

    reducer = umap.UMAP(
        metric="precomputed",
        n_components=2,
        n_neighbors=30,
        min_dist=0.08,
        random_state=42,
    )
    coordinates = reducer.fit_transform(distances)
    return {
        node: (float(coordinates[index[node], 0]), float(coordinates[index[node], 1]))
        for node in nodes
    }


def graph_to_d3_data(graph, layout, group_key, note=None):
    if graph.number_of_nodes() == 0:
        return empty_d3_data(layout, group_key)

    ranked_nodes = sorted(
        graph.nodes,
        key=lambda node: (
            graph.nodes[node].get("centrality", 0.0),
            graph.nodes[node].get("weighted_degree", 0.0),
        ),
        reverse=True,
    )
    labelled_nodes = set(ranked_nodes[:45])

    data = {
        "layout": layout,
        "group_key": group_key,
        "note": note,
        "nodes": [],
        "links": [],
    }
    for node in ranked_nodes:
        attrs = graph.nodes[node]
        data["nodes"].append(
            {
                "id": str(node),
                "name": attrs.get("name") or str(node),
                "ticker": attrs.get("ticker"),
                "sector": attrs.get("sector") or "Unknown",
                "family": attrs.get("family") or "Other",
                "component": attrs.get("component"),
                "community": attrs.get("community") or attrs.get("component"),
                "degree": int(attrs.get("degree", graph.degree(node))),
                "weighted_degree": float(
                    attrs.get("weighted_degree", graph.degree(node, weight="weight"))
                ),
                "centrality": float(attrs.get("centrality", 0.0)),
                "pagerank": float(attrs.get("pagerank", 0.0)),
                "component_size": int(attrs.get("component_size", 1)),
                "show_label": node in labelled_nodes,
                "x": attrs.get("x"),
                "y": attrs.get("y"),
            }
        )
    for source, target, attrs in graph.edges(data=True):
        data["links"].append(
            {
                "source": str(source),
                "target": str(target),
                "weight": int(attrs.get("weight", 1)),
            }
        )
    return data


def empty_d3_data(layout, group_key):
    return {"layout": layout, "group_key": group_key, "nodes": [], "links": []}


def component_summary(graph, limit=10):
    rows = []
    components = sorted(nx.connected_components(graph), key=len, reverse=True)
    for index, component in enumerate(components[:limit], start=1):
        subgraph = graph.subgraph(component)
        hubs = [
            graph.nodes[node]["name"]
            for node, _ in sorted(
                subgraph.degree(weight="weight"), key=lambda item: item[1], reverse=True
            )[:5]
        ]
        rows.append(
            {
                "Island": index,
                "Companies": subgraph.number_of_nodes(),
                "Edges": subgraph.number_of_edges(),
                "Density": f"{nx.density(subgraph):.4f}",
                "Top hubs": "; ".join(hubs),
            }
        )
    return rows


def write_json(output_dir, filename, data):
    with open(os.path.join(output_dir, filename), "w") as handle:
        json.dump(data, handle)


def write_network_index(output_dir, full_graph, nonisolated_graph):
    html = network_index_html(full_graph, nonisolated_graph)
    with open(os.path.join(output_dir, "network.html"), "w") as handle:
        handle.write(html)


def write_graph_page(
    output_dir,
    html_filename,
    title,
    subtitle,
    data_filename,
    data,
    table_rows,
    table_title="Largest Islands",
):
    write_json(output_dir, data_filename, data)
    html = graph_page_html(
        title=title,
        subtitle=subtitle,
        data_filename=data_filename,
        data=data,
        table_rows=table_rows,
        table_title=table_title,
    )
    with open(os.path.join(output_dir, html_filename), "w") as handle:
        handle.write(html)


def network_index_html(full_graph, nonisolated_graph):
    nontrivial_components = sum(
        1 for component in nx.connected_components(full_graph) if len(component) > 1
    )
    cards = "\n".join(
        f"""
        <a class="network-card" href="{link['href']}">
            <h2>{link['title']}</h2>
            <p>{link['description']}</p>
        </a>
        """
        for link in NETWORK_PAGE_LINKS
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Company Director Network</title>
    <link rel="stylesheet" href="css/style.css">
    <style>{inline_network_css()}</style>
</head>
<body>
    <header>
        <h1>Company Director Network</h1>
        <p>Reduced views of companies connected by shared directors.</p>
        <nav>
            <div class="nav-links">
                <a href="index.html">Back to Directory</a>
                <a href="progress.html">Processing Progress</a>
            </div>
        </nav>
    </header>

    <div class="container">
        <h2>Network Shape</h2>
        <div class="network-metrics">
            <div><strong>{full_graph.number_of_nodes():,}</strong><span>companies in source graph</span></div>
            <div><strong>{nonisolated_graph.number_of_nodes():,}</strong><span>companies with shared-director links</span></div>
            <div><strong>{full_graph.number_of_edges():,}</strong><span>shared-director edges</span></div>
            <div><strong>{nontrivial_components:,}</strong><span>non-trivial islands</span></div>
        </div>
    </div>

    <div class="network-card-grid">
        {cards}
    </div>

    <div class="footnote">
        <p>Edges count distinct shared directors between companies.</p>
    </div>
</body>
</html>"""


def graph_page_html(title, subtitle, data_filename, data, table_rows, table_title):
    rows_html = table_html(table_rows)
    note_html = f"<p>{data.get('note')}</p>" if data.get("note") else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <link rel="stylesheet" href="css/style.css">
    <style>{inline_network_css()}</style>
</head>
<body>
    <header>
        <h1>{title}</h1>
        <p>{subtitle}</p>
        <nav>
            <div class="nav-links">
                <a href="network.html">Network Index</a>
                <a href="index.html">Directory</a>
            </div>
        </nav>
    </header>

    <div class="container">
        <div class="network-metrics">
            <div><strong>{len(data['nodes']):,}</strong><span>companies shown</span></div>
            <div><strong>{len(data['links']):,}</strong><span>edges shown</span></div>
            <div><strong>{data['layout']}</strong><span>layout</span></div>
            <div><strong>{data['group_key']}</strong><span>color grouping</span></div>
        </div>
        {note_html}
        <div id="network" class="network-canvas"></div>
    </div>

    <div class="container">
        <h2>{table_title}</h2>
        {rows_html}
    </div>

    <script>
    const dataFile = "{data_filename}";
    {network_d3_script()}
    </script>
</body>
</html>"""


def table_html(rows):
    if not rows:
        return "<p>No rows available.</p>"
    headers = list(rows[0].keys())
    header_html = "".join(f"<th>{header}</th>" for header in headers)
    row_html = []
    for row in rows:
        row_html.append(
            "<tr>"
            + "".join(f"<td>{row.get(header, '')}</td>" for header in headers)
            + "</tr>"
        )
    return f"""
    <table>
        <thead><tr>{header_html}</tr></thead>
        <tbody>{''.join(row_html)}</tbody>
    </table>
    """


def inline_network_css():
    return """
    .network-card-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
        gap: 16px;
        margin-bottom: 20px;
    }
    .network-card {
        display: block;
        background: white;
        border-radius: 6px;
        padding: 18px;
        box-shadow: 0 2px 5px rgba(0, 0, 0, 0.1);
        color: var(--text-color);
    }
    .network-card h2 {
        color: var(--primary-color);
        font-size: 1.1rem;
        margin-bottom: 8px;
    }
    .network-card:hover {
        text-decoration: none;
        transform: translateY(-2px);
    }
    .network-metrics {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 12px;
        margin-bottom: 16px;
    }
    .network-metrics div {
        background: var(--light-gray);
        border-radius: 6px;
        padding: 12px;
    }
    .network-metrics strong {
        display: block;
        color: var(--primary-color);
        font-size: 1.3rem;
    }
    .network-metrics span {
        display: block;
        color: var(--dark-gray);
        font-size: 0.9rem;
    }
    .network-canvas svg {
        width: 100%;
        height: 760px;
        border: 1px solid var(--light-gray);
        background: #fff;
    }
    .network-label {
        font-size: 10px;
        pointer-events: none;
        paint-order: stroke;
        stroke: white;
        stroke-width: 3px;
        stroke-linejoin: round;
    }
    .network-tooltip {
        position: absolute;
        background: rgba(44, 62, 80, 0.94);
        color: white;
        padding: 8px 10px;
        border-radius: 4px;
        font-size: 12px;
        pointer-events: none;
        max-width: 300px;
    }
    """


def network_d3_script():
    return r"""
    fetch(dataFile).then(response => response.json()).then(data => {
        const container = document.getElementById('network');
        const width = Math.max(900, container.clientWidth || 900);
        const height = 760;
        const svg = d3.select(container).append('svg')
            .attr('viewBox', `0 0 ${width} ${height}`);

        if (!data.nodes.length) {
            svg.append('text').attr('x', 30).attr('y', 40).text('No nodes to display.');
            return;
        }

        const groupKey = data.group_key || 'component';
        const color = d3.scaleOrdinal([
            '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
            '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
            '#4e79a7', '#f28e2b', '#59a14f', '#e15759', '#76b7b2',
            '#edc948', '#b07aa1', '#ff9da7', '#9c755f', '#bab0ab'
        ]);
        const maxMetric = d3.max(data.nodes, d => d.centrality || d.pagerank || d.degree || 1) || 1;
        const radius = d => {
            const metric = d.centrality || d.pagerank || d.degree || 1;
            return Math.max(3, Math.min(17, 3 + 14 * Math.sqrt(metric / maxMetric)));
        };

        const tooltip = d3.select('body').append('div')
            .attr('class', 'network-tooltip')
            .style('display', 'none');

        const idMap = new Map(data.nodes.map(d => [d.id, d]));
        const linkLayer = svg.append('g');
        const nodeLayer = svg.append('g');
        const labelLayer = svg.append('g');

        function linkNode(value) {
            return typeof value === 'object' ? value : idMap.get(String(value));
        }

        const link = linkLayer.selectAll('line')
            .data(data.links)
            .enter().append('line')
            .attr('stroke', '#95a5a6')
            .attr('stroke-opacity', d => Math.min(0.55, 0.12 + d.weight * 0.04))
            .attr('stroke-width', d => Math.min(5, Math.sqrt(d.weight)));

        const node = nodeLayer.selectAll('circle')
            .data(data.nodes)
            .enter().append('circle')
            .attr('r', radius)
            .attr('fill', d => color(String(d[groupKey] || 'Other')))
            .attr('stroke', '#263238')
            .attr('stroke-width', 0.6)
            .on('mousemove', (event, d) => {
                tooltip
                    .style('display', 'block')
                    .style('left', `${event.pageX + 12}px`)
                    .style('top', `${event.pageY + 12}px`)
                    .html(`<strong>${d.name}</strong><br>${d.ticker || 'No ticker'}<br>${groupKey}: ${d[groupKey] || 'Other'}<br>degree: ${d.degree}; weighted degree: ${d.weighted_degree.toFixed(1)}`);
            })
            .on('mouseleave', () => tooltip.style('display', 'none'));

        const label = labelLayer.selectAll('text')
            .data(data.nodes.filter(d => d.show_label))
            .enter().append('text')
            .attr('class', 'network-label')
            .text(d => d.ticker || d.name)
            .attr('dx', 8)
            .attr('dy', 3);

        if (data.layout === 'fixed') {
            const xExtent = d3.extent(data.nodes, d => d.x);
            const yExtent = d3.extent(data.nodes, d => d.y);
            const x = d3.scaleLinear().domain(xExtent).nice().range([40, width - 40]);
            const y = d3.scaleLinear().domain(yExtent).nice().range([height - 40, 40]);

            link
                .attr('x1', d => x(linkNode(d.source).x))
                .attr('y1', d => y(linkNode(d.source).y))
                .attr('x2', d => x(linkNode(d.target).x))
                .attr('y2', d => y(linkNode(d.target).y));
            node
                .attr('cx', d => x(d.x))
                .attr('cy', d => y(d.y));
            label
                .attr('x', d => x(d.x))
                .attr('y', d => y(d.y));
            return;
        }

        const simulation = d3.forceSimulation(data.nodes)
            .force('link', d3.forceLink(data.links)
                .id(d => d.id)
                .distance(d => Math.max(28, 130 - Math.min(95, d.weight * 12)))
                .strength(d => Math.min(0.45, 0.05 + d.weight * 0.015)))
            .force('charge', d3.forceManyBody().strength(-42))
            .force('collide', d3.forceCollide(d => radius(d) + 2))
            .force('center', d3.forceCenter(width / 2, height / 2));

        node.call(d3.drag()
            .on('start', (event, d) => {
                if (!event.active) simulation.alphaTarget(0.3).restart();
                d.fx = d.x;
                d.fy = d.y;
            })
            .on('drag', (event, d) => {
                d.fx = event.x;
                d.fy = event.y;
            })
            .on('end', (event, d) => {
                if (!event.active) simulation.alphaTarget(0);
                d.fx = null;
                d.fy = null;
            }));

        simulation.on('tick', () => {
            link
                .attr('x1', d => d.source.x)
                .attr('y1', d => d.source.y)
                .attr('x2', d => d.target.x)
                .attr('y2', d => d.target.y);
            node
                .attr('cx', d => d.x)
                .attr('cy', d => d.y);
            label
                .attr('x', d => d.x)
                .attr('y', d => d.y);
        });
    });
    """


def write_centrality_price_analysis(output_dir, conn, company_graph):
    rows, records = centrality_price_rows(conn, company_graph)

    correlations_path = os.path.join(output_dir, "network_centrality_price_correlations.csv")
    with open(correlations_path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)

    records_path = os.path.join(output_dir, "network_centrality_price_records.csv")
    if records:
        with open(records_path, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(records[0].keys()))
            writer.writeheader()
            writer.writerows(records)

    html = centrality_price_html(rows, len(records))
    with open(os.path.join(output_dir, "network-centrality-price.html"), "w") as handle:
        handle.write(html)


def centrality_price_rows(conn, company_graph):
    analysis_graph = strip_isolates(company_graph)
    add_component_metrics(analysis_graph)
    company_features = company_centrality_features(analysis_graph)
    director_features = director_centrality_features(conn)
    filing_rows = fetch_filing_price_boards(conn)

    records = []
    previous_by_company = {}
    for row in filing_rows:
        cik = row["cikcode"]
        previous = previous_by_company.get(cik)
        if previous and previous["close_price"] and row["close_price"]:
            growth = (
                (row["close_price"] - previous["close_price"])
                / previous["close_price"]
                * 100.0
            )
            previous_directors = previous["directors"]
            board_metrics = board_director_features(previous_directors, director_features)
            company_metrics = company_features.get(cik, {})
            record = {
                "cikcode": cik,
                "ticker": previous["ticker"],
                "from_date": previous["filingdate"].isoformat(),
                "to_date": row["filingdate"].isoformat(),
                "growth_pct": growth,
                "abs_growth_pct": abs(growth),
            }
            record.update(company_metrics)
            record.update(board_metrics)
            records.append(record)
        previous_by_company[cik] = row

    feature_labels = {
        "company_degree": "Company degree",
        "company_weighted_degree": "Company weighted degree",
        "company_pagerank": "Company PageRank",
        "company_eigenvector": "Company eigenvector",
        "company_closeness": "Company closeness",
        "company_betweenness": "Company betweenness",
        "board_avg_director_degree": "Board avg director degree",
        "board_max_director_degree": "Board max director degree",
        "board_avg_director_weighted_degree": "Board avg director weighted degree",
        "board_max_director_weighted_degree": "Board max director weighted degree",
        "board_avg_director_pagerank": "Board avg director PageRank",
        "board_max_director_pagerank": "Board max director PageRank",
    }
    correlation_rows = []
    for target_key, target_label in (
        ("growth_pct", "Next filing-to-filing return"),
        ("abs_growth_pct", "Absolute filing-to-filing return"),
    ):
        for feature_key, feature_label in feature_labels.items():
            xs = []
            ys = []
            for record in records:
                value = record.get(feature_key)
                target = record.get(target_key)
                if value is None or target is None:
                    continue
                xs.append(float(value))
                ys.append(float(target))
            stats = correlation_stats(xs, ys)
            if not stats:
                continue
            correlation_rows.append(
                {
                    "Feature": feature_label,
                    "Target": target_label,
                    "N": stats["n"],
                    "Pearson r": fmt_float(stats["pearson_r"]),
                    "Pearson p": fmt_p(stats["pearson_p"]),
                    "Spearman rho": fmt_float(stats["spearman_r"]),
                    "Spearman p": fmt_p(stats["spearman_p"]),
                }
            )

    correlation_rows.sort(
        key=lambda row: abs(float(row["Spearman rho"])) if row["Spearman rho"] else 0.0,
        reverse=True,
    )
    return correlation_rows, records


def company_centrality_features(graph):
    features = {}
    if graph.number_of_nodes() == 0:
        return features

    pagerank = nx.pagerank(graph, weight="weight")
    closeness = nx.closeness_centrality(graph)
    betweenness = nx.betweenness_centrality(
        graph, k=min(250, graph.number_of_nodes()), seed=42, weight=None
    )
    eigenvector = {}
    for component in nx.connected_components(graph):
        subgraph = graph.subgraph(component)
        if subgraph.number_of_edges() == 0:
            continue
        try:
            component_eigenvector = nx.eigenvector_centrality(
                subgraph, weight="weight", max_iter=1000
            )
        except nx.PowerIterationFailedConvergence:
            component_eigenvector = {node: 0.0 for node in subgraph.nodes}
        eigenvector.update(component_eigenvector)

    for node in graph.nodes:
        features[node] = {
            "company_degree": graph.degree(node),
            "company_weighted_degree": graph.degree(node, weight="weight"),
            "company_pagerank": pagerank.get(node, 0.0),
            "company_eigenvector": eigenvector.get(node, 0.0),
            "company_closeness": closeness.get(node, 0.0),
            "company_betweenness": betweenness.get(node, 0.0),
        }
    return features


def director_centrality_features(conn):
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT DISTINCT cikcode, director_name
          FROM company_directorships
         WHERE director_name IS NOT NULL
        """
    )
    rows = cursor.fetchall()
    cursor.close()

    company_directors = defaultdict(list)
    for cik, director_name in rows:
        company_directors[cik].append(director_name)

    graph = nx.Graph()
    for directors in company_directors.values():
        unique_directors = sorted(set(directors))
        graph.add_nodes_from(unique_directors)
        for director1, director2 in itertools.combinations(unique_directors, 2):
            if graph.has_edge(director1, director2):
                graph[director1][director2]["weight"] += 1
            else:
                graph.add_edge(director1, director2, weight=1)

    if graph.number_of_nodes() == 0:
        return {}

    pagerank = nx.pagerank(graph, weight="weight", max_iter=100)
    features = {}
    for director in graph.nodes:
        features[director] = {
            "degree": graph.degree(director),
            "weighted_degree": graph.degree(director, weight="weight"),
            "pagerank": pagerank.get(director, 0.0),
        }
    return features


def fetch_filing_price_boards(conn):
    cursor = conn.cursor()
    cursor.execute(
        """
        WITH filing_prices AS (
            SELECT f.cikcode,
                   f.accessionnumber,
                   f.filingdate,
                   t.ticker,
                   sp.close_price::float AS close_price,
                   row_number() OVER (
                       PARTITION BY f.cikcode, f.accessionnumber
                       ORDER BY t.ticker
                   ) AS ticker_rank
              FROM filings f
              JOIN cik_to_ticker t ON f.cikcode = t.cikcode
              JOIN stock_prices sp
                ON sp.ticker = t.ticker
               AND sp.price_date = f.filingdate
             WHERE f.form = 'DEF 14A'
        )
        SELECT p.cikcode,
               p.accessionnumber,
               p.filingdate,
               p.ticker,
               p.close_price,
               array_agg(DISTINCT dm.director_name) AS directors
          FROM filing_prices p
          JOIN director_mentions dm
            ON dm.cikcode = p.cikcode
           AND dm.accessionnumber = p.accessionnumber
         WHERE p.ticker_rank = 1
         GROUP BY p.cikcode, p.accessionnumber, p.filingdate, p.ticker, p.close_price
         ORDER BY p.cikcode, p.filingdate
        """
    )
    rows = []
    for cikcode, accessionnumber, filingdate, ticker, close_price, directors in cursor.fetchall():
        rows.append(
            {
                "cikcode": cikcode,
                "accessionnumber": accessionnumber,
                "filingdate": filingdate,
                "ticker": ticker,
                "close_price": close_price,
                "directors": directors or [],
            }
        )
    cursor.close()
    return rows


def board_director_features(directors, director_features):
    values = [director_features.get(director) for director in directors]
    values = [value for value in values if value]
    if not values:
        return {
            "board_avg_director_degree": None,
            "board_max_director_degree": None,
            "board_avg_director_weighted_degree": None,
            "board_max_director_weighted_degree": None,
            "board_avg_director_pagerank": None,
            "board_max_director_pagerank": None,
        }
    degrees = [value["degree"] for value in values]
    weighted_degrees = [value["weighted_degree"] for value in values]
    pageranks = [value["pagerank"] for value in values]
    return {
        "board_avg_director_degree": mean(degrees),
        "board_max_director_degree": max(degrees),
        "board_avg_director_weighted_degree": mean(weighted_degrees),
        "board_max_director_weighted_degree": max(weighted_degrees),
        "board_avg_director_pagerank": mean(pageranks),
        "board_max_director_pagerank": max(pageranks),
    }


def mean(values):
    return sum(values) / len(values) if values else None


def correlation_stats(xs, ys):
    if len(xs) < 4 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    from scipy.stats import pearsonr, spearmanr

    pearson_result = pearsonr(xs, ys)
    spearman_result = spearmanr(xs, ys)
    if math.isnan(pearson_result.statistic) or math.isnan(spearman_result.statistic):
        return None
    return {
        "n": len(xs),
        "pearson_r": float(pearson_result.statistic),
        "pearson_p": float(pearson_result.pvalue),
        "spearman_r": float(spearman_result.statistic),
        "spearman_p": float(spearman_result.pvalue),
    }


def fmt_float(value):
    if value is None or math.isnan(value):
        return ""
    return f"{value:.4f}"


def fmt_p(value):
    if value is None or math.isnan(value):
        return ""
    return f"{value:.4f}" if value >= 0.0001 else f"{value:.2e}"


def centrality_price_html(rows, record_count):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Centrality and Price Activity</title>
    <link rel="stylesheet" href="css/style.css">
    <style>{inline_network_css()}</style>
</head>
<body>
    <header>
        <h1>Centrality and Price Activity</h1>
        <p>Exploratory filing-to-filing correlations using company and director graph centrality features.</p>
        <nav>
            <div class="nav-links">
                <a href="network.html">Network Index</a>
                <a href="index.html">Directory</a>
            </div>
        </nav>
    </header>

    <div class="container">
        <h2>Analysis Notes</h2>
        <p>This is a rough exploratory screen, not a causal model. For each company, the features are measured at a prior DEF 14A filing and compared with the price change to the next priced DEF 14A filing.</p>
        <p>Director centrality is computed in a director co-board graph. Company centrality is computed in the shared-director company graph.</p>
        <div class="network-metrics">
            <div><strong>{record_count:,}</strong><span>filing-to-filing price records</span></div>
            <div><strong>2</strong><span>targets: return and absolute return</span></div>
            <div><strong>CSV</strong><span>correlations and record-level data written beside this page</span></div>
        </div>
    </div>

    <div class="container">
        <h2>Strongest Correlations</h2>
        {table_html(rows[:40])}
    </div>

    <div class="footnote">
        <p>Generated files: network_centrality_price_correlations.csv and network_centrality_price_records.csv.</p>
    </div>
</body>
</html>"""
