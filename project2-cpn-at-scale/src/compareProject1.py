"""
compareProject1.py - Part C consistency check: Project 1 SIUE program graphs vs.
the new SIUE extractions (CS, ECE, BIOL).

Project 1 graphs were built from per-degree-program CSV files; the Project 2
graphs are "all department courses + transitive prerequisites" extracted from
the institutional CPN. This script reports the exact node/edge set differences
and checks whether every Project 1 edge exists in the institutional SIUE CPN.

Run from the project2-cpn-at-scale folder:
    .venv/bin/python src/compareProject1.py [--project1-dir PATH]

--project1-dir overrides config.project1Dir, the folder holding CS.gml, ECE.gml
and BIOL.gml from Project 1.
"""
import argparse
import csv
from pathlib import Path

import networkx as nx

import config
from cpnCommon import courseDepartments, loadInstitutionGraph


def loadProject1Graph(program):
    path = config.project1Dir / f"{program}.gml"
    return nx.read_gml(path, label="label") if path.exists() else None


def main():
    siue = loadInstitutionGraph("SIUE")
    summaryRows, detailRows = [], []
    for program in config.programOrder:
        oldGraph = loadProject1Graph(program)
        if oldGraph is None:
            summaryRows.append({"program": program, "status": "PENDING - Project 1 GML not found"})
            continue
        newGraph = nx.read_gml(config.extractedGraphDir / f"SIUE_{program}.gml", label="label")
        oldNodes, newNodes = set(oldGraph), set(newGraph)
        oldEdges, newEdges = set(oldGraph.edges()), set(newGraph.edges())
        reversedOld = {(v, u) for u, v in oldEdges}
        onlyOld, onlyNew = oldNodes - newNodes, newNodes - oldNodes
        # Where do Project-1-only nodes/edges come from?
        onlyOldInSiue = {n for n in onlyOld if n in siue}
        oldEdgesInSiue = {e for e in oldEdges if siue.has_edge(*e)}
        summaryRows.append({
            "program": program, "status": "compared",
            "project1Nodes": len(oldNodes), "project1Edges": len(oldEdges),
            "project2Nodes": len(newNodes), "project2Edges": len(newEdges),
            "sharedNodes": len(oldNodes & newNodes), "sharedEdges": len(oldEdges & newEdges),
            "nodesOnlyInProject1": len(onlyOld), "nodesOnlyInProject2": len(onlyNew),
            "edgesOnlyInProject1": len(oldEdges - newEdges), "edgesOnlyInProject2": len(newEdges - oldEdges),
            "project1EdgesSameDirectionInSIUE": len(oldEdgesInSiue),
            "project1EdgesReversedVsProject2": len(reversedOld & newEdges),
            "project1OnlyNodesPresentInSIUE": len(onlyOldInSiue),
            "identicalGraphs": oldNodes == newNodes and oldEdges == newEdges,
        })
        for node in sorted(onlyOld):
            # The institutional CPN merges cross-listed / co-requisite courses into one
            # node ("PHYS141/PHYS151L/PHYS151"); look for the course inside such labels.
            mergedInto = [n for n in siue if node in n.split("/") and n != node]
            if node in siue:
                note = "in SIUE CPN under the same label"
            elif mergedInto:
                note = f"merged in SIUE CPN as {mergedInto[0]}"
            else:
                note = "NOT in SIUE CPN under any label"
            detailRows.append({"program": program, "type": "node only in Project 1", "item": node, "note": note})
        for node in sorted(onlyNew):
            role = ("department course" if config.programMappings["SIUE"][program][0]
                    in courseDepartments(node) else "prerequisite from other dept")
            detailRows.append({"program": program, "type": "node only in Project 2", "item": node,
                               "note": f"{role}; degree in extraction {newGraph.degree(node)}"})
        for u, v in sorted(oldEdges - newEdges):
            note = "edge exists in SIUE CPN" if siue.has_edge(u, v) else (
                "REVERSED edge exists in SIUE CPN" if siue.has_edge(v, u) else "not in SIUE CPN")
            detailRows.append({"program": program, "type": "edge only in Project 1", "item": f"{u} -> {v}", "note": note})
        for u, v in sorted(newEdges - oldEdges):
            detailRows.append({"program": program, "type": "edge only in Project 2", "item": f"{u} -> {v}", "note": ""})

    outDir = config.programTablesDir
    keys = []
    for row in summaryRows:
        keys += [k for k in row if k not in keys]
    with open(outDir / "project1_vs_project2_SIUE_summary.csv", "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(summaryRows)
    with open(outDir / "project1_vs_project2_SIUE_differences.csv", "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["program", "type", "item", "note"])
        writer.writeheader()
        writer.writerows(detailRows)
    for row in summaryRows:
        print(row)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare Project 1 SIUE graphs with the Project 2 extractions.")
    parser.add_argument("--project1-dir", type=Path, default=config.project1Dir,
                        help="folder with the Project 1 CS.gml, ECE.gml and BIOL.gml (default: %(default)s)")
    config.project1Dir = parser.parse_args().project1_dir
    main()
