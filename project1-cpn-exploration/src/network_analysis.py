"""
Run with: python src/network_analysis.py
Purpose: Analyze five course prerequisite networks and save result tables.

Reads BIOL.csv, CS.csv, ECE.csv, MATH.csv and ME.csv from data/ and writes
four CSV tables to results/. Set DATA_DIR or RESULTS_DIR to use other folders.
Every analysis uses prerequisite -> dependent course edges.
"""

import csv
import os
from pathlib import Path
from statistics import mean, median

import networkx as nx


# Locate inputs relative to the project folder, rather than the terminal folder.
projectFolder = Path(__file__).resolve().parent.parent
dataFolder = Path(os.environ.get("DATA_DIR", projectFolder / "data"))

# Reuse the output folder if it exists. The four CSV tables are replaced each run.
resultsFolder = Path(os.environ.get("RESULTS_DIR", projectFolder / "results"))
resultsFolder.mkdir(parents=True, exist_ok=True)

programNames = ["BIOL", "CS", "ECE", "MATH", "ME"]


def buildCourseGraph(csvPath):
    """Read a headerless CSV, reverse its edges, and verify it is a DAG.

    Each row names a course followed by its prerequisites. Return a graph
    whose arrows lead toward dependent courses; raise ValueError on a cycle.
    """

    # Initially follow the CSV wording: course -> its prerequisite.
    rawGraph = nx.DiGraph()

    with open(csvPath, newline="", encoding="utf-8-sig") as csvFile:
        for csvRow in csv.reader(csvFile):
            # Ignore empty lines and rows containing only whitespace or blanks.
            if not csvRow or not any(csvEntry.strip() for csvEntry in csvRow):
                continue

            courseName = csvRow[0].strip()

            # Preserve courses even when they have no prerequisites.
            rawGraph.add_node(courseName)

            for csvEntry in csvRow[1:]:
                prerequisiteName = csvEntry.strip()

                if prerequisiteName:
                    # DiGraph automatically adds any new endpoint nodes.
                    # Repeated edges do not create parallel copies.
                    rawGraph.add_edge(courseName, prerequisiteName)

    # Reverse course -> prerequisite into prerequisite -> dependent course.
    # copy=True keeps rawGraph unchanged and returns a separate graph.
    courseGraph = rawGraph.reverse(copy=True)

    # A cycle would make a course depend indirectly on itself. Stop here:
    # topological ordering and DAG longest paths require an acyclic graph.
    if not nx.is_directed_acyclic_graph(courseGraph):
        raise ValueError(f"{csvPath.name} contains a directed cycle.")

    return courseGraph


def saveTable(fileName, tableRows):
    """Save a nonempty list of dictionaries as a CSV in resultsFolder.

    Each dictionary represents one row and must have the same keys.
    Keys in the first row determine the column headings and their order.
    """

    outputPath = resultsFolder / fileName

    with open(outputPath, "w", newline="", encoding="utf-8") as outputFile:
        csvWriter = csv.DictWriter(
            outputFile,
            fieldnames=list(tableRows[0].keys())
        )
        csvWriter.writeheader()
        csvWriter.writerows(tableRows)


# Collect one kind of result per list, combining all five programs.
# Summary: one row per program. Course: one row per course.
# Ranking: five rows per program. Strata: one row per dependency level.
summaryRows = []
courseRows = []
rankingRows = []
strataRows = []


for programName in programNames:
    csvPath = dataFolder / f"{programName}.csv"
    courseGraph = buildCourseGraph(csvPath)

    nodeCount = courseGraph.number_of_nodes()
    edgeCount = courseGraph.number_of_edges()

    # Reach counts distinct courses reachable along outgoing directed paths.
    # It includes immediate and indirect dependents, excluding the start.
    # A course reached through several different paths is counted only once.
    reachScores = {}

    for courseName in courseGraph:
        downstreamCourses = nx.descendants(courseGraph, courseName)
        reachScores[courseName] = len(downstreamCourses)

    # Betweenness measures how often a course lies inside shortest paths
    # between other courses. Equally short paths share the credit.
    # The DiGraph makes paths directed; weight=None gives every edge equal cost.
    # endpoints=False excludes path endpoints. Normalization divides by
    # (nodeCount - 1) * (nodeCount - 2) for these networks.
    # A source can have high reach but zero betweenness.
    betweennessScores = nx.betweenness_centrality(
        courseGraph,
        normalized=True,
        weight=None,
        endpoints=False
    )

    # A topological order places prerequisites before their dependents.
    # Lexicographical sorting chooses alphabetically among available nodes,
    # making this order consistent across repeated runs on the same graph.
    topologicalOrder = list(
        nx.lexicographical_topological_sort(courseGraph)
    )

    # Dynamic programming in topological order finds one longest path.
    # Other paths can tie for maximum length. topo_order is NetworkX's
    # required keyword, so that API name must remain in snake_case.
    longestPath = nx.dag_longest_path(
        courseGraph,
        topo_order=topologicalOrder
    )

    # Depth counts edges, not courses: nine courses means eight edges.
    # This differs from diameter, which is based on shortest paths.
    depthEdges = len(longestPath) - 1

    # Stratum 0 contains sources, which have no incoming prerequisite edges.
    # Each other course has level 1 plus its highest prerequisite level.
    # These are dependency levels, not guaranteed semester schedules.
    # Sorting within a generation only makes the table easier to read.
    topologicalStrata = [
        sorted(courseGeneration)
        for courseGeneration in nx.topological_generations(courseGraph)
    ]

    # Record each course's level for lookup when building the course table.
    courseStratumNumbers = {}

    for stratumNumber, stratumCourses in enumerate(topologicalStrata):
        strataRows.append({
            "Program": programName,
            "Stratum": stratumNumber,
            "CourseCount": len(stratumCourses),
            "Courses": "; ".join(stratumCourses)
        })

        for courseName in stratumCourses:
            courseStratumNumbers[courseName] = stratumNumber

    # Export all courses alphabetically, including those with zero scores.
    # ReachFraction divides by the number of OTHER courses, allowing
    # comparisons between program sizes. All five inputs have >1 course.
    for courseName in sorted(courseGraph):
        courseRows.append({
            "Program": programName,
            "Course": courseName,
            "Reach": reachScores[courseName],
            "ReachFraction": reachScores[courseName] / (nodeCount - 1),
            "Betweenness": betweennessScores[courseName],
            "Stratum": courseStratumNumbers[courseName]
        })

    # sorted() is ascending by default. Negating scores puts larger ones first.
    # Course names break ties alphabetically; [:5] keeps only the top five.
    topReachCourses = sorted(
        reachScores,
        key=lambda courseName: (-reachScores[courseName], courseName)
    )[:5]

    topBetweennessCourses = sorted(
        betweennessScores,
        key=lambda courseName: (-betweennessScores[courseName], courseName)
    )[:5]

    # Pair equal rank positions from two independent lists; their courses
    # may differ. All supplied programs have at least five courses.
    # Add one to Python's zero-based index to report ranks 1 through 5.
    for rankIndex in range(5):
        reachCourse = topReachCourses[rankIndex]
        betweennessCourse = topBetweennessCourses[rankIndex]

        rankingRows.append({
            "Program": programName,
            "Rank": rankIndex + 1,
            "ReachCourse": reachCourse,
            "Reach": reachScores[reachCourse],
            "BetweennessCourse": betweennessCourse,
            "Betweenness": betweennessScores[betweennessCourse]
        })

    # Zero reach means no downstream courses within this graph. It does not
    # mean the course is unimportant or optional. In sum(), True counts as
    # 1 and False as 0, so these comparisons count terminal courses.
    zeroReachCount = sum(
        reachScore == 0 for reachScore in reachScores.values()
    )

    # Weak components are connected groups when arrow direction is ignored.
    # For a nonempty DAG, number of strata equals depth in edges plus one.
    # Mean, median, and maximum describe the distribution of course reach.
    summaryRows.append({
        "Program": programName,
        "Nodes": nodeCount,
        "Edges": edgeCount,
        "DepthEdges": depthEdges,
        "NumberOfStrata": len(topologicalStrata),
        "WeakComponents": nx.number_weakly_connected_components(
            courseGraph
        ),
        "MeanReach": mean(reachScores.values()),
        "MedianReach": median(reachScores.values()),
        "MaximumReach": max(reachScores.values()),
        "MeanReachFraction": mean(reachScores.values()) / (nodeCount - 1),
        "ZeroReachCount": zeroReachCount,
        "LongestPath": " -> ".join(longestPath)
    })

    # Print a short progress summary. Rounding applies only to this display;
    # the CSV tables retain the full computed betweenness precision.
    print(f"\n{programName}")
    print(f"Courses: {nodeCount}, edges: {edgeCount}")
    print(f"Depth: {depthEdges} edges")
    print(f"Number of strata: {len(topologicalStrata)}")
    print("Longest path:", " -> ".join(longestPath))
    print(
        "Highest reach:",
        topReachCourses[0],
        reachScores[topReachCourses[0]]
    )
    print(
        "Highest betweenness:",
        topBetweennessCourses[0],
        round(betweennessScores[topBetweennessCourses[0]], 6)
    )


# Write all four tables after every program has been analyzed.
# Keep filenames and column headings stable across runs.
saveTable("program_summary.csv", summaryRows)
saveTable("course_metrics.csv", courseRows)
saveTable("top5_comparison.csv", rankingRows)
saveTable("topological_strata.csv", strataRows)

print("\nTables saved to:", resultsFolder)
