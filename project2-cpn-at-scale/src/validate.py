"""
validate.py - Independent checks on every output. Writes results/tables/validation_report.csv
and prints PASS/FAIL per check. Exit code 1 if anything fails.

Run from the project2-cpn-at-scale folder (after partB_networkx.py and gephiPipeline.py):
    .venv/bin/python src/validate.py
"""
import csv
import random
import sys
import zipfile

import networkx as nx

import config
from cpnCommon import bfsTreeSize, computeStrata, departmentNodes, loadInstitutionGraph

results = []


def check(name, passed, detail=""):
    results.append({"check": name, "result": "PASS" if passed else "FAIL", "detail": detail})
    print(f"[{'PASS' if passed else 'FAIL'}] {name} {('- ' + detail) if detail else ''}")


def readCsv(path):
    with open(path, newline="") as handle:
        return list(csv.DictReader(handle))


def main():
    graphs = {inst: loadInstitutionGraph(inst) for inst in config.institutionFiles}

    # ---- Input checks -----------------------------------------------------------
    for inst, g in graphs.items():
        cycles = list(nx.simple_cycles(g)) if not nx.is_directed_acyclic_graph(g) else []
        check(f"{inst}: input is directed and acyclic", g.is_directed() and not cycles,
              f"{len(cycles)} cycles" if cycles else "DAG")

    # ---- 15 program GML files ------------------------------------------------------
    gmlFiles = sorted(config.extractedGraphDir.glob("*.gml"))
    check("exactly 15 program GML files", len(gmlFiles) == 15, f"found {len(gmlFiles)}")
    programSummary = {(r["institution"], r["program"]): r
                      for r in readCsv(config.programTablesDir / "program_summary.csv")}
    programStrata = readCsv(config.programTablesDir / "program_strata_distribution.csv")
    for inst, g in graphs.items():
        for program in config.programOrder:
            path = config.extractedGraphDir / f"{inst}_{program}.gml"
            tag = f"{inst} {program}"
            try:
                sub = nx.read_gml(path, label="label")
            except Exception as error:   # noqa: BLE001
                check(f"{tag}: GML reads back", False, str(error))
                continue
            check(f"{tag}: GML reads back as directed graph", sub.is_directed(),
                  f"{sub.number_of_nodes()} nodes, {sub.number_of_edges()} edges")
            nodes = set(sub)
            wanted = departmentNodes(g, config.programMappings[inst][program])
            check(f"{tag}: every department node included", wanted <= nodes,
                  f"{len(wanted)} dept nodes, missing {len(wanted - nodes)}")
            missingPrereqs = {a for n in nodes for a in nx.ancestors(g, n)} - nodes
            check(f"{tag}: transitive prerequisites closed", not missingPrereqs,
                  f"missing {len(missingPrereqs)}")
            check(f"{tag}: edges equal induced edges of original", set(sub.edges()) == set(g.subgraph(nodes).edges()))
            check(f"{tag}: original labels and attr1 preserved",
                  all(n in g and sub.nodes[n].get("attr1") == g.nodes[n].get("attr1") for n in nodes))
            check(f"{tag}: no extra nodes beyond dept courses + prerequisites",
                  nodes == wanted | {a for n in wanted for a in nx.ancestors(g, n)})
            stratumOf = {n: int(sub.nodes[n]["stratum"]) for n in sub}
            check(f"{tag}: strata respect every edge",
                  all(stratumOf[v] > stratumOf[u] for u, v in sub.edges()) and stratumOf == computeStrata(sub))
            row = programSummary[(inst, program)]
            check(f"{tag}: summary CSV totals match graph",
                  int(row["nodes"]) == sub.number_of_nodes() and int(row["edges"]) == sub.number_of_edges()
                  and int(row["targetDeptCourses"]) == len(wanted)
                  and int(row["maxStratum_edges"]) == max(stratumOf.values()))
            strataRows = [r for r in programStrata if r["institution"] == inst and r["program"] == program]
            check(f"{tag}: stratum CSV sums to node count",
                  sum(int(r["courseCount"]) for r in strataRows) == sub.number_of_nodes()
                  and abs(sum(float(r["percent"]) for r in strataRows) - 100) < 1e-6)
            metrics = readCsv(config.programTablesDir / "course_metrics" / f"{inst}_{program}_course_metrics.csv")
            check(f"{tag}: course-metrics CSV has one row per node", len(metrics) == sub.number_of_nodes())

    # ---- Institution tables -----------------------------------------------------------
    summary = {r["institution"]: r for r in readCsv(config.institutionTablesDir / "institution_summary.csv")}
    strata = readCsv(config.institutionTablesDir / "strata_distribution_all.csv")
    rng = random.Random(490)
    for inst, g in graphs.items():
        row = summary[inst]
        check(f"{inst}: summary nodes/edges/components match graph",
              int(row["nodes"]) == g.number_of_nodes() and int(row["edges"]) == g.number_of_edges()
              and int(row["weakComponents"]) == nx.number_weakly_connected_components(g))
        stratumOf = computeStrata(g)
        check(f"{inst}: strata respect every prerequisite edge",
              all(stratumOf[v] > stratumOf[u] for u, v in g.edges()))
        check(f"{inst}: max stratum equals DAG longest path (edges)",
              max(stratumOf.values()) == nx.dag_longest_path_length(g) == int(row["maxStratum_edges"]))
        instStrata = [r for r in strata if r["institution"] == inst]
        check(f"{inst}: stratum CSV sums to node count",
              sum(int(r["courseCount"]) for r in instStrata) == g.number_of_nodes())
        metrics = {r["course"]: r for r in readCsv(config.institutionTablesDir / f"{inst}_course_metrics.csv")}
        check(f"{inst}: course-metrics CSV has one row per node", len(metrics) == g.number_of_nodes())
        check(f"{inst}: CSV strata equal recomputed strata",
              all(int(metrics[n]["stratum"]) == s for n, s in stratumOf.items()))
        # Reach vs. an independent BFS on representative courses: top-5, sinks,
        # isolates and a seeded random sample.
        topCourses = [r["course"] for r in readCsv(config.institutionTablesDir / "reach_top5.csv")
                      if r["institution"] == inst]
        sample = topCourses + rng.sample(sorted(g), 40)
        sample += [n for n in sorted(g) if g.out_degree(n) == 0][:3] + list(nx.isolates(g))[:3]
        badReach = [n for n in sample
                    if int(metrics[n]["reach"]) != bfsTreeSize(g, n)
                    or int(metrics[n]["reach"]) != len(nx.descendants(g, n)) + 1
                    or int(metrics[n]["descendantCount"]) != len(nx.descendants(g, n))]
        check(f"{inst}: reach agrees with BFS on {len(sample)} representative courses", not badReach,
              f"mismatches: {badReach[:5]}")

    # ---- Gephi vs. NetworkX cross-checks -----------------------------------------------
    gephiStats = readCsv(config.gephiTablesDir / "institution_gephi_statistics.csv")
    for inst, g in graphs.items():
        full = [r for r in gephiStats if r["institution"] == inst and r["graph"] == "full"][0]
        check(f"{inst}: Gephi node/edge/weak-component counts equal NetworkX",
              int(full["nodes"]) == g.number_of_nodes() and int(full["edges"]) == g.number_of_edges()
              and int(full["weakComponents"]) == int(summary[inst]["weakComponents"])
              and int(full["giantComponentSize"]) == int(summary[inst]["largestComponentSize"]))
        check(f"{inst}: Gephi avg path length equals NetworkX (reachable pairs)",
              abs(float(full["avgPathLength"]) - float(summary[inst]["avgShortestPathLength"])) < 1e-6,
              f"Gephi {float(full['avgPathLength']):.6f} vs NX {float(summary[inst]['avgShortestPathLength']):.6f}")
        check(f"{inst}: Gephi diameter equals NetworkX longest shortest path",
              int(float(full["diameter"])) == int(summary[inst]["diameterReachable"]))
        gephiNodes = {r["Label"]: r for r in readCsv(config.gephiTablesDir / "institutions" / f"{inst}_gephi_nodes.csv")}
        metrics = {r["course"]: r for r in readCsv(config.institutionTablesDir / f"{inst}_course_metrics.csv")}
        maxDiff = max(abs(float(gephiNodes[n]["betweenesscentrality"]) - float(metrics[n]["betweennessExact"]))
                      for n in metrics)
        check(f"{inst}: Gephi directed betweenness equals NetworkX exact betweenness", maxDiff < 1e-6,
              f"max abs diff {maxDiff:.2e}")
        check(f"{inst}: Gephi in/out-degree equal NetworkX",
              all(int(gephiNodes[n]["indegree"]) == int(metrics[n]["inDegree"]) and
                  int(gephiNodes[n]["outdegree"]) == int(metrics[n]["outDegree"]) for n in metrics))
        lccRows = readCsv(config.gephiTablesDir / "institutions" / f"{inst}_LCC_gephi_nodes_modularity.csv")
        resolutionCols = [f"modClass_res{str(r).replace('.', '_')}" for r in config.modularityResolutions]
        check(f"{inst}: all three modularity memberships preserved on LCC",
              len(lccRows) == int(summary[inst]["largestComponentSize"]) and
              all(c in lccRows[0] and all(r[c] != "" for r in lccRows) for c in resolutionCols))
    programGephi = {(r["institution"], r["program"]): r
                    for r in readCsv(config.gephiTablesDir / "program_gephi_statistics.csv")}
    check("Gephi program stats exist for all 15 programs", len(programGephi) == 15)
    for (inst, program), r in programGephi.items():
        s = programSummary[(inst, program)]
        check(f"{inst} {program}: Gephi import counts equal extraction",
              int(r["nodes"]) == int(s["nodes"]) and int(r["edges"]) == int(s["edges"])
              and int(r["weakComponents"]) == int(s["weakComponents"]))

    # ---- Gephi artifacts ----------------------------------------------------------------
    projects = sorted(config.gephiProjectDir.glob("institutions/*.gephi")) + \
        sorted(config.gephiProjectDir.glob("programs/*.gephi"))
    valid = [p for p in projects if zipfile.is_zipfile(p) and zipfile.ZipFile(p).testzip() is None]
    check("20 Gephi project files (5 institutions + 15 programs) are valid archives",
          len(valid) == 20, f"{len(valid)} valid of {len(projects)}")
    pdfs = list(config.gephiFigureDir.glob("**/*.pdf"))
    check("Gephi PDF exports present (25 institutional + 30 program)", len(pdfs) == 55, f"found {len(pdfs)}")

    config.tablesDir.mkdir(exist_ok=True)
    with open(config.tablesDir / "validation_report.csv", "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["check", "result", "detail"])
        writer.writeheader()
        writer.writerows(results)
    failed = [r for r in results if r["result"] == "FAIL"]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
