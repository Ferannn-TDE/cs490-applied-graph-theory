"""
Run with: python src/cpn_analysis.py [PROGRAM ...]
Purpose: Build course prerequisite networks and export them for Gephi.

PROGRAM is one or more of BIOL, CS, ECE, MATH, ME (default: all five).
Input CSVs are read from data/ and GML files are written to results/gml/.
Set DATA_DIR or RESULTS_DIR to use other folders.
Each CSV row contains a course followed by its prerequisites, with no header.
"""

import csv
import os
import sys
from pathlib import Path

import networkx as nx


# Resolve paths relative to the project folder, even when run from elsewhere.
projectFolder = Path(__file__).resolve().parent.parent
dataFolder = Path(os.environ.get("DATA_DIR", projectFolder / "data"))
gmlFolder = Path(os.environ.get("RESULTS_DIR", projectFolder / "results")) / "gml"
gmlFolder.mkdir(parents=True, exist_ok=True)

programNames = sys.argv[1:] or ["BIOL", "CS", "ECE", "MATH", "ME"]

for programName in programNames:
    # The program name controls both the input CSV and the exported GML filename.
    csvPath = dataFolder / f"{programName}.csv"
    outputPath = gmlFolder / f"{programName}.gml"

    # A DiGraph stores directed edges: the order of the courses matters.
    # First follow the CSV wording: course -> its prerequisite.
    rawGraph = nx.DiGraph()

    with open(csvPath, newline="", encoding="utf-8-sig") as csvFile:
        csvReader = csv.reader(csvFile)

        for csvRow in csvReader:
            # A completely empty line contains no course to add.
            if not csvRow:
                continue

            # The first cell identifies this row's course. Remove surrounding spaces.
            courseName = csvRow[0].strip()

            # Explicitly retain the course even if it has no prerequisites or edges.
            rawGraph.add_node(courseName)

            # Each remaining nonempty cell names a prerequisite for this course.
            for csvEntry in csvRow[1:]:
                prerequisiteName = csvEntry.strip()

                if prerequisiteName:
                    # Missing endpoint nodes are added automatically by NetworkX.
                    # Repeating an edge does not create a duplicate in a DiGraph.
                    rawGraph.add_edge(courseName, prerequisiteName)

    # Transposition reverses every edge but keeps the same courses.
    # For example, CS456 -> CS340 becomes CS340 -> CS456.
    # Outgoing paths now lead from prerequisites to their dependent courses.
    # copy=True creates a separate graph and leaves rawGraph unchanged.
    courseGraph = rawGraph.reverse(copy=True)

    print(f"\n{programName}")
    print("Number of courses:", courseGraph.number_of_nodes())
    print("Number of edges:", courseGraph.number_of_edges())

    # A DAG has no directed cycle: no directed path returns to its starting node.
    # Here we display the check; it does not prevent the GML export below.
    # The separate analysis script stops on cycles because its algorithms need a DAG.
    print("Is the graph a DAG?", nx.is_directed_acyclic_graph(courseGraph))

    # GML preserves course labels and edge direction for import into Gephi.
    # Running this script again replaces the GML for the selected program.
    nx.write_gml(courseGraph, outputPath)
    print("Graph saved to:", outputPath)
