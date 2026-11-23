"""
partB_networkx.py - Part B: NetworkX analysis of the five institutional CPNs and
extraction/analysis of the 15 degree-program subgraphs.

Run from the project2-cpn-at-scale folder:
    .venv/bin/python src/partB_networkx.py

Outputs (under results/, or RESULTS_DIR if set)
    tables/institutions/*.csv   whole-CPN statistics, strata, reach, components
    tables/programs/*.csv       program-subgraph statistics, strata, node metrics
    graphs/*.gml                the 15 program subgraphs
    figures/networkx/*.png      comparison charts and layered program drawings
"""
import csv
import statistics
from collections import Counter, defaultdict

import matplotlib
matplotlib.use("Agg")                     # file output only, no window
import matplotlib.pyplot as plt
import networkx as nx

import config
from cpnCommon import (computeReach, computeStrata, courseDepartments,
                       departmentNodes, directedPathStatistics,
                       extractProgramGraph, loadInstitutionGraph, primaryDepartment, rankedCounts,
                       stratumDistribution, topKWithTies, weakComponentSummary)

# Reference categorical palette (validated colour-blind-safe order, slots 1-5).
institutionColors = dict(zip(config.institutionFiles,
                             ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]))
programColors = dict(zip(config.programOrder, ["#2a78d6", "#eb6834", "#1baf7a"]))
inkColor, mutedColor, gridColor = "#0b0b0b", "#52514e", "#e4e3df"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def writeCsv(path, rows, fieldNames=None):
    """Write a list of dict rows to CSV (creates parent folders)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    fieldNames = fieldNames or list(rows[0].keys())
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldNames)
        writer.writeheader()
        writer.writerows(rows)


def styleAxes(ax, title, xLabel, yLabel):
    """Recessive grid/axes; text in ink colours, never series colours."""
    ax.set_title(title, loc="left", fontsize=11, color=inkColor)
    ax.set_xlabel(xLabel, color=mutedColor)
    ax.set_ylabel(yLabel, color=mutedColor)
    ax.grid(axis="y", color=gridColor, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(gridColor)
    ax.tick_params(colors=mutedColor)


def saveFigure(fig, name):
    config.networkxFigureDir.mkdir(parents=True, exist_ok=True)
    fig.savefig(config.networkxFigureDir / name, dpi=200, bbox_inches="tight")
    plt.close(fig)


def nodeMetricRows(graph, stratumOf, descendantCount, reach, extra=None):
    """Per-course metrics shared by the institution and program tables.

    Betweenness is EXACT (Brandes' algorithm over all sources), directed and
    unnormalised so it is directly comparable with Gephi's directed betweenness.
    PageRank uses alpha = 0.85 like Gephi's default.
    """
    betweenness = nx.betweenness_centrality(graph, normalized=False)
    pageRank = nx.pagerank(graph, alpha=config.pageRankAlpha)
    componentOf = {}
    for compId, comp in enumerate(sorted(nx.weakly_connected_components(graph),
                                         key=lambda c: (-len(c), min(c)))):
        for node in comp:
            componentOf[node] = (compId, len(comp))
    rows = []
    for node in sorted(graph.nodes()):
        row = {
            "course": node,
            "primaryDept": primaryDepartment(graph, node),
            "allDepts": "/".join(courseDepartments(node)),
            "isCrossListed": int("/" in node and len(courseDepartments(node)) > 1),
            "inDegree": graph.in_degree(node),
            "outDegree": graph.out_degree(node),
            "stratum": stratumOf[node],
            "descendantCount": descendantCount[node],
            "reach": reach[node],
            "betweennessExact": betweenness[node],
            "pageRank": pageRank[node],
            "weakComponentId": componentOf[node][0],
            "weakComponentSize": componentOf[node][1],
        }
        if extra:
            row.update(extra(node))
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Whole-institution analysis
# ---------------------------------------------------------------------------
def analyzeInstitution(institution, graph):
    """Compute and export everything Part B.1 asks for one institution."""
    outDir = config.institutionTablesDir
    stratumOf = computeStrata(graph)
    descendantCount, reach = computeReach(graph)
    components, componentStats = weakComponentSummary(graph)
    pathStats = directedPathStatistics(graph)

    # Per-course table
    metricRows = nodeMetricRows(graph, stratumOf, descendantCount, reach)
    writeCsv(outDir / f"{institution}_course_metrics.csv", metricRows)

    # Stratum distribution
    distRows = stratumDistribution(stratumOf)
    for row in distRows:
        row["institution"] = institution
    # Department composition per stratum. A cross-listed course counts once for
    # EACH department in its label ("department appearances"), so per-stratum
    # sums can exceed the course count; courseCount is reported alongside.
    compositionRows = []
    byStratum = defaultdict(Counter)
    for node, s in stratumOf.items():
        for dept in courseDepartments(node):
            byStratum[s][dept] += 1
    stratumSize = Counter(stratumOf.values())
    for s in sorted(byStratum):
        for dept, count in byStratum[s].most_common():
            compositionRows.append({"institution": institution, "stratum": s,
                                    "dept": dept, "deptAppearances": count,
                                    "coursesInStratum": stratumSize[s]})
    # Deep-strata department summary (stratum >= threshold)
    deepCounter, deepExamples = Counter(), defaultdict(list)
    deepNodes = [n for n, s in stratumOf.items() if s >= config.deepStratumThreshold]
    for node in sorted(deepNodes, key=lambda n: (-stratumOf[n], n)):
        for dept in courseDepartments(node):
            deepCounter[dept] += 1
            if len(deepExamples[dept]) < 4:
                deepExamples[dept].append(f"{node}(s{stratumOf[node]})")
    deepRows = [{"institution": institution, "dept": dept, "deptAppearancesDeep": c,
                 "percentOfDeepCourses": 100.0 * c / len(deepNodes),
                 "deptTotalCourses": sum(1 for n in graph if dept in courseDepartments(n)),
                 "exampleDeepCourses": "; ".join(deepExamples[dept])}
                for dept, c in deepCounter.most_common()]

    # Reach top-5 with ties
    topRows = []
    for row in topKWithTies(reach, config.topK):
        topRows.append({"institution": institution, "rank": row["rank"],
                        "course": row["course"], "reach": row["score"],
                        "descendantCount": row["score"] - 1,
                        "stratum": stratumOf[row["course"]],
                        "outDegree": graph.out_degree(row["course"]),
                        "tiedWithOthers": row["tiedWith"]})

    # Weak component size distribution + intermediate components
    sizeCounts = Counter(len(c) for c in components)
    componentSizeRows = [{"institution": institution, "componentSize": size,
                          "numberOfComponents": count}
                         for size, count in sorted(sizeCounts.items(), reverse=True)]
    intermediateRows = []
    for rank, comp in enumerate(components[1:], start=2):
        if len(comp) < 2:
            continue
        sub = graph.subgraph(comp)
        deptCounts = Counter(d for n in comp for d in courseDepartments(n))
        intermediateRows.append({
            "institution": institution, "componentRank": rank, "size": len(comp),
            "edges": sub.number_of_edges(),
            "maxStratumWithin": max(computeStrata(sub).values()),
            "deptComposition": "; ".join(f"{d}:{c}" for d, c in rankedCounts(deptCounts)),
            "dominantDeptShare": round(deptCounts.most_common(1)[0][1] / len(comp), 3),
            "exampleCourses": "; ".join(sorted(comp)[:8]),
        })

    reachValues = list(reach.values())
    summary = {
        "institution": institution,
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "density": nx.density(graph),
        "isDAG": nx.is_directed_acyclic_graph(graph),
        "selfLoops": nx.number_of_selfloops(graph),
        "departments": len({primaryDepartment(graph, n) for n in graph} - {"MERGED"}),
        "crossListedNodes": sum(1 for n in graph if len(courseDepartments(n)) > 1),
        "isolatedNodes": nx.number_of_isolates(graph),
        "roots_inDegree0": sum(1 for n in graph if graph.in_degree(n) == 0),
        "sinks_outDegree0": sum(1 for n in graph if graph.out_degree(n) == 0),
        **componentStats,
        "maxStratum_edges": max(stratumOf.values()),
        "longestChain_courses": max(stratumOf.values()) + 1,
        "dagLongestPath_check": nx.dag_longest_path_length(graph),
        "meanReach": statistics.mean(reachValues),
        "medianReach": statistics.median(reachValues),
        "maxReach": max(reachValues),
        "percentReach1": 100.0 * sum(1 for r in reachValues if r == 1) / len(reachValues),
        "reachablePairs": pathStats["reachablePairs"],
        "reachablePairFraction": pathStats["reachablePairFraction"],
        "avgShortestPathLength": pathStats["avgShortestPathLength"],
        "diameterReachable": pathStats["diameterReachable"],
    }
    pathRows = [{"institution": institution, "pathLength": d, "orderedPairs": c}
                for d, c in pathStats["pathLengthCounts"].items()]
    return {"summary": summary, "strata": distRows, "composition": compositionRows,
            "deep": deepRows, "top": topRows, "componentSizes": componentSizeRows,
            "intermediate": intermediateRows, "paths": pathRows, "reach": reach,
            "stratumOf": stratumOf, "components": components}


# ---------------------------------------------------------------------------
# Program subgraph extraction + analysis
# ---------------------------------------------------------------------------
def analyzeProgram(institution, program, deptCodes, graph, export=True):
    """Extract one program graph, export it, and compute its statistics."""
    subgraph, seeds = extractProgramGraph(graph, deptCodes)
    stratumOf = computeStrata(subgraph)
    descendantCount, reach = computeReach(subgraph)
    components, componentStats = weakComponentSummary(subgraph)
    pathStats = directedPathStatistics(subgraph)

    summary = {
        "institution": institution, "program": program,
        "deptCodes": "+".join(deptCodes),
        "targetDeptCourses": len(seeds),
        "crossListedTargetCourses": sum(1 for n in seeds if len(courseDepartments(n)) > 1),
        "isolatedTargetCourses": sum(1 for n in seeds if subgraph.degree(n) == 0),
        "prerequisiteOnlyCourses": subgraph.number_of_nodes() - len(seeds),
        "nodes": subgraph.number_of_nodes(), "edges": subgraph.number_of_edges(),
        **componentStats,
        "maxStratum_edges": max(stratumOf.values()),
        "longestChain_courses": max(stratumOf.values()) + 1,
        "meanReach": statistics.mean(reach.values()),
        "maxReach": max(reach.values()),
        "reachablePairs": pathStats["reachablePairs"],
        "avgShortestPathLength": pathStats["avgShortestPathLength"],
        "diameterReachable": pathStats["diameterReachable"],
    }
    if not export:
        return summary

    # Store analysis attributes on the nodes, then export GML. NetworkX writes
    # the node key (the original course label) as the GML 'label'.
    for node in subgraph.nodes():
        subgraph.nodes[node]["stratum"] = stratumOf[node]
        subgraph.nodes[node]["reach"] = reach[node]
    subgraph.graph = {"institution": institution, "program": program,
                      "deptCodes": "+".join(deptCodes)}
    config.extractedGraphDir.mkdir(parents=True, exist_ok=True)
    nx.write_gml(subgraph, config.extractedGraphDir / f"{institution}_{program}.gml")

    metricRows = nodeMetricRows(subgraph, stratumOf, descendantCount, reach,
                                extra=lambda n: {"isTargetDept": int(n in seeds)})
    writeCsv(config.programTablesDir / "course_metrics" / f"{institution}_{program}_course_metrics.csv",
             metricRows)

    distRows = stratumDistribution(stratumOf)
    targetPerStratum = Counter(stratumOf[n] for n in seeds)
    for row in distRows:
        row.update({"institution": institution, "program": program,
                    "targetDeptCourses": targetPerStratum[row["stratum"]]})
    # Which departments supply the prerequisite-only courses?
    supplierCounts = Counter(primaryDepartment(subgraph, n)
                             for n in subgraph if n not in seeds)
    supplierRows = [{"institution": institution, "program": program, "dept": d,
                     "prerequisiteCourses": c} for d, c in rankedCounts(supplierCounts)]
    topRows = [{"institution": institution, "program": program, **r}
               for r in topKWithTies(reach, config.topK)]
    return {"summary": summary, "strata": distRows, "suppliers": supplierRows,
            "top": topRows, "graph": subgraph, "stratumOf": stratumOf, "seeds": seeds}


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------
def plotInstitutionCharts(results):
    institutions = list(results)
    xs = range(len(institutions))
    colors = [institutionColors[i] for i in institutions]

    # 1. Size, components and depth - separate panels (different units).
    fig, axes = plt.subplots(1, 4, figsize=(16, 3.8))
    panels = [("nodes", "Courses (nodes)"), ("edges", "Prerequisite edges"),
              ("weakComponents", "Weak components"), ("maxStratum_edges", "Max stratum (edges)")]
    for ax, (key, title) in zip(axes, panels):
        values = [results[i]["summary"][key] for i in institutions]
        bars = ax.bar(xs, values, color=colors, width=0.6)
        ax.bar_label(bars, labels=[f"{v:,}" for v in values], fontsize=8, color=inkColor, padding=2)
        ax.set_xticks(list(xs), institutions)
        styleAxes(ax, title, "", "")
    fig.suptitle("Institutional CPN size, connectivity and depth (NetworkX)", x=0.01, ha="left")
    fig.tight_layout()
    saveFigure(fig, "institution_size_components_depth.png")

    # 2. Largest weak component share vs. singleton share.
    fig, ax = plt.subplots(figsize=(7, 3.8))
    width = 0.38
    lcc = [results[i]["summary"]["largestComponentPercent"] for i in institutions]
    single = [100.0 * results[i]["summary"]["singletonComponents"] / results[i]["summary"]["nodes"]
              for i in institutions]
    b1 = ax.bar([x - width / 2 for x in xs], lcc, width, color="#2a78d6", label="Largest weak component")
    b2 = ax.bar([x + width / 2 for x in xs], single, width, color="#eb6834", label="Singleton (isolated) courses")
    for bars in (b1, b2):
        ax.bar_label(bars, fmt="%.1f%%", fontsize=8, color=inkColor, padding=2)
    ax.set_xticks(list(xs), institutions)
    ax.legend(frameon=False, fontsize=8)
    styleAxes(ax, "Share of courses in the largest component vs. isolated (NetworkX)", "", "% of courses")
    saveFigure(fig, "institution_component_shares.png")

    # 3. Stratum distribution (percent of courses), log scale because stratum 0 dominates.
    fig, ax = plt.subplots(figsize=(8, 4.2))
    for inst in institutions:
        rows = results[inst]["strata"]
        ax.plot([r["stratum"] for r in rows], [r["percent"] for r in rows], marker="o",
                markersize=5, linewidth=2, color=institutionColors[inst], label=inst)
    ax.set_yscale("log")
    ax.legend(frameon=False, fontsize=8, ncol=5)
    styleAxes(ax, "Courses per topological stratum (NetworkX)", "Stratum (0 = no prerequisites)",
              "% of courses (log scale)")
    saveFigure(fig, "institution_strata_distribution.png")

    # 4. Reach complementary CDF: fraction of courses with reach >= r.
    fig, ax = plt.subplots(figsize=(8, 4.2))
    for inst in institutions:
        values = sorted(results[inst]["reach"].values())
        n = len(values)
        distinct = sorted(set(values))
        ccdf = [sum(1 for v in values if v >= r) / n for r in distinct]
        ax.step(distinct, ccdf, where="post", linewidth=2, color=institutionColors[inst], label=inst)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.legend(frameon=False, fontsize=8, ncol=5)
    styleAxes(ax, "Reach distribution: share of courses with reach >= r (NetworkX)",
              "Reach r (BFS tree size, includes the course itself)", "Share of courses")
    saveFigure(fig, "institution_reach_ccdf.png")

    # 5. Top-5 reach per institution (small multiples, single-series panels).
    fig, axes = plt.subplots(1, len(institutions), figsize=(18, 3.6))
    for ax, inst in zip(axes, institutions):
        rows = results[inst]["top"]
        labels = [f'{r["rank"]}. {r["course"]}' for r in rows][::-1]
        values = [r["reach"] for r in rows][::-1]
        bars = ax.barh(range(len(rows)), values, color=institutionColors[inst], height=0.6)
        ax.bar_label(bars, fontsize=8, color=inkColor, padding=2)
        ax.set_yticks(range(len(rows)), labels, fontsize=8)
        styleAxes(ax, inst, "Reach", "")
        ax.grid(axis="x", color=gridColor)
        ax.grid(axis="y", visible=False)
    fig.suptitle("Top-5 courses by reach (ties included; NetworkX)", x=0.01, ha="left")
    fig.tight_layout()
    saveFigure(fig, "institution_top_reach.png")


def plotProgramCharts(programResults):
    institutions = list(config.institutionFiles)
    xs = list(range(len(institutions)))
    width = 0.26
    for key, title, fileName in [
        ("nodes", "Program subgraph size (courses incl. prerequisites)", "program_nodes.png"),
        ("edges", "Program subgraph prerequisite edges", "program_edges.png"),
        ("maxStratum_edges", "Program subgraph max stratum (edges)", "program_max_stratum.png"),
        ("weakComponents", "Program subgraph weak components", "program_weak_components.png"),
    ]:
        fig, ax = plt.subplots(figsize=(8, 4))
        for k, program in enumerate(config.programOrder):
            values = [programResults[(i, program)]["summary"][key] for i in institutions]
            bars = ax.bar([x + (k - 1) * width for x in xs], values, width,
                          color=programColors[program], label=program)
            ax.bar_label(bars, fontsize=7, color=inkColor, padding=2)
        ax.set_xticks(xs, institutions)
        ax.legend(frameon=False, fontsize=8, ncol=3)
        styleAxes(ax, title + " (NetworkX)", "", "")
        saveFigure(fig, fileName)

    # Stratum distributions: one panel per program, one line per institution.
    fig, axes = plt.subplots(1, 3, figsize=(16, 4), sharey=True)
    for ax, program in zip(axes, config.programOrder):
        for inst in institutions:
            rows = programResults[(inst, program)]["strata"]
            ax.plot([r["stratum"] for r in rows], [r["percent"] for r in rows], marker="o",
                    markersize=4, linewidth=2, color=institutionColors[inst], label=inst)
        styleAxes(ax, program, "Stratum", "% of program-graph courses")
    axes[0].legend(frameon=False, fontsize=8)
    fig.suptitle("Program subgraph stratum distributions (NetworkX)", x=0.01, ha="left")
    fig.tight_layout()
    saveFigure(fig, "program_strata_distribution.png")


def drawLayeredProgram(result, institution, program):
    """Layered drawing: x = stratum, target-department courses highlighted."""
    graph, stratumOf, seeds = result["graph"], result["stratumOf"], result["seeds"]
    for node in graph:
        graph.nodes[node]["layer"] = stratumOf[node]
    pos = nx.multipartite_layout(graph, subset_key="layer", align="vertical", scale=1.0)
    n = graph.number_of_nodes()
    fig, ax = plt.subplots(figsize=(14, max(6, min(40, n * 0.06))))
    nx.draw_networkx_edges(graph, pos, ax=ax, edge_color="#b9b8b2", width=0.5,
                           arrows=True, arrowsize=5, node_size=30)
    others = [v for v in graph if v not in seeds]
    nx.draw_networkx_nodes(graph, pos, nodelist=others, node_color="#9b9a95", node_size=30, ax=ax,
                           label="Prerequisite from another department")
    nx.draw_networkx_nodes(graph, pos, nodelist=list(seeds), node_color=programColors[program],
                           node_size=30, ax=ax, label=f"{program} department course")
    nx.draw_networkx_labels(graph, pos, font_size=4 if n > 150 else 6, ax=ax,
                            verticalalignment="bottom", font_color=inkColor)
    ax.set_title(f"{institution} {program} program subgraph - layered by stratum (NetworkX); "
                 f"{n} courses, {graph.number_of_edges()} edges", loc="left", fontsize=11)
    ax.legend(frameon=False, fontsize=8, loc="upper right")
    ax.axis("off")
    for node in graph:
        del graph.nodes[node]["layer"]
    saveFigure(fig, f"layered_{institution}_{program}.png")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    graphs = {inst: loadInstitutionGraph(inst)
              for inst in config.institutionFiles}

    # ---- Whole-CPN analysis ----------------------------------------------
    results = {}
    for inst, graph in graphs.items():
        print(f"[institution] {inst}: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges")
        results[inst] = analyzeInstitution(inst, graph)
    outDir = config.institutionTablesDir
    writeCsv(outDir / "institution_summary.csv", [r["summary"] for r in results.values()])
    gather = lambda key: [row for r in results.values() for row in r[key]]
    writeCsv(outDir / "strata_distribution_all.csv", gather("strata"),
             ["institution", "stratum", "courseCount", "percent"])
    writeCsv(outDir / "strata_department_composition.csv", gather("composition"))
    writeCsv(outDir / "deep_strata_departments.csv", gather("deep"))
    writeCsv(outDir / "reach_top5.csv", gather("top"))
    writeCsv(outDir / "weak_component_size_distribution.csv", gather("componentSizes"))
    writeCsv(outDir / "intermediate_weak_components.csv", gather("intermediate"))
    writeCsv(outDir / "directed_path_length_distribution.csv", gather("paths"))
    # Wide stratum table (stratum x institution, counts and percents) for the report
    maxS = max(r["summary"]["maxStratum_edges"] for r in results.values())
    wide = []
    for s in range(maxS + 1):
        row = {"stratum": s}
        for inst, r in results.items():
            match = [x for x in r["strata"] if x["stratum"] == s]
            row[f"{inst}_count"] = match[0]["courseCount"] if match else 0
            row[f"{inst}_percent"] = round(match[0]["percent"], 2) if match else 0.0
        wide.append(row)
    writeCsv(outDir / "strata_distribution_wide.csv", wide)
    plotInstitutionCharts(results)

    # ---- Program subgraphs --------------------------------------------------
    programResults = {}
    for inst, graph in graphs.items():
        for program in config.programOrder:
            codes = config.programMappings[inst][program]
            programResults[(inst, program)] = analyzeProgram(inst, program, codes, graph)
            s = programResults[(inst, program)]["summary"]
            print(f"[program] {inst} {program} ({'+'.join(codes)}): {s['nodes']} nodes, "
                  f"{s['edges']} edges, max stratum {s['maxStratum_edges']}")
    pDir = config.programTablesDir
    writeCsv(pDir / "program_summary.csv", [r["summary"] for r in programResults.values()])
    writeCsv(pDir / "program_strata_distribution.csv",
             [row for r in programResults.values() for row in r["strata"]],
             ["institution", "program", "stratum", "courseCount", "percent", "targetDeptCourses"])
    writeCsv(pDir / "program_prerequisite_supplier_departments.csv",
             [row for r in programResults.values() for row in r["suppliers"]])
    writeCsv(pDir / "program_reach_top5.csv",
             [row for r in programResults.values() for row in r["top"]])

    # ---- Mapping inspection and sensitivity variants -------------------------
    mappingRows = []
    for inst, graph in graphs.items():
        deptCounts = Counter(d for n in graph for d in courseDepartments(n))
        for program in config.programOrder:
            for code in config.programMappings[inst][program]:
                mappingRows.append({"institution": inst, "program": program, "deptCode": code,
                                    "nodesContainingCode": deptCounts.get(code, 0),
                                    "usedInPrimaryMapping": 1})
        for (sInst, sProgram), codes in config.sensitivityMappings.items():
            if sInst == inst:
                for code in codes:
                    if code not in config.programMappings[inst][sProgram]:
                        mappingRows.append({"institution": inst, "program": sProgram, "deptCode": code,
                                            "nodesContainingCode": deptCounts.get(code, 0),
                                            "usedInPrimaryMapping": 0})
    writeCsv(pDir / "department_mapping_inspection.csv", mappingRows)
    sensitivityRows = []
    for (inst, program), codes in config.sensitivityMappings.items():
        s = analyzeProgram(inst, program, codes, graphs[inst], export=False)
        s["variant"] = "sensitivity (not exported)"
        sensitivityRows.append(s)
        p = dict(programResults[(inst, program)]["summary"])
        p["variant"] = "primary (exported GML)"
        sensitivityRows.append(p)
    writeCsv(pDir / "mapping_sensitivity.csv", sensitivityRows)

    plotProgramCharts(programResults)
    for (inst, program), result in programResults.items():
        drawLayeredProgram(result, inst, program)
    print("Part B complete.")


if __name__ == "__main__":
    main()
