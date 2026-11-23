"""
cpnCommon.py - Shared graph-loading and graph-algorithm helpers (NetworkX).

Conventions used everywhere in this project
-------------------------------------------
* Nodes are identified by their original course label (e.g. "CS150" or the
  cross-listed "CS374/ECE374"). Labels were verified to be unique per graph.
* Edge direction is prerequisite -> dependent course (u -> v means "u must be
  taken before v"). This was checked on known pairs, e.g. ACCT200 -> ACCT210.
* Stratum: roots (in-degree 0) are stratum 0; every other node is
  1 + max(stratum of its predecessors). The maximum stratum is the longest
  prerequisite chain measured in EDGES; the chain in COURSES is max stratum + 1.
* Reach (BFS tree size) INCLUDES the starting course: reach = descendants + 1.
"""
import re
from collections import Counter, deque

import networkx as nx

import config

# A course token is a run of capital letters (the department code) followed by
# the course number, e.g. "COMPSCI1575", "ECE466", "NURSE490AP2".
deptPattern = re.compile(r"^([A-Z]+)")


def loadInstitutionGraph(institution):
    """Read an institutional GML file and re-key nodes by their course label.

    The GML files use integer ids plus a 'label' attribute. We relabel to the
    course label so that node names are meaningful and comparable across files.
    The original integer id is kept as the 'gmlId' node attribute.
    """
    path = config.inputDir / config.institutionFiles[institution]
    rawGraph = nx.read_gml(path, label="id")
    if not rawGraph.is_directed():
        raise ValueError(f"{path} is not a directed graph")
    labelOf = {n: d["label"] for n, d in rawGraph.nodes(data=True)}
    if len(set(labelOf.values())) != len(labelOf):
        raise ValueError(f"{path} has duplicate course labels")
    graph = nx.DiGraph()
    for nodeId, data in rawGraph.nodes(data=True):
        attrs = {k: v for k, v in data.items() if k != "label"}
        attrs["gmlId"] = nodeId
        graph.add_node(data["label"], **attrs)
    graph.add_edges_from((labelOf[u], labelOf[v]) for u, v in rawGraph.edges())
    graph.graph["institution"] = institution
    return graph


def rankedCounts(counter):
    """Return (key, count) pairs, largest count first, ties broken alphabetically.

    Counter.most_common() keeps insertion order for ties, and that order follows
    set iteration, which changes between runs. Sorting makes output repeatable.
    """
    return sorted(counter.items(), key=lambda item: (-item[1], item[0]))


def courseDepartments(label):
    """Return the list of department codes in a (possibly cross-listed) label.

    "MATH447/CS447" -> ["MATH", "CS"];  "CE330/CE330L" -> ["CE"].
    """
    depts = []
    for token in label.split("/"):
        match = deptPattern.match(token.strip())
        if match and match.group(1) not in depts:
            depts.append(match.group(1))
    return depts


def primaryDepartment(graph, node):
    """Department used for single-valued partitions (tables, colours).

    Non-cross-listed nodes use the attr1 field from the GML. Cross-listed nodes
    are attr1 == "MERGED" in the source data and are kept as "MERGED" so the
    category stays faithful to the input.
    """
    return graph.nodes[node].get("attr1") or courseDepartments(node)[0]


# ---------------------------------------------------------------------------
# Topological stratification
# ---------------------------------------------------------------------------
def computeStrata(graph):
    """Longest-path layering of a DAG.

    Algorithm: process nodes in topological order (Kahn's order guarantees every
    prerequisite is processed before its dependents). A root gets stratum 0;
    any other node gets 1 + the largest stratum among its predecessors. This is
    the length (in edges) of the longest prerequisite chain ending at the node.
    Runs in O(V + E). Raises if the graph has a cycle (strata are undefined).
    """
    if not nx.is_directed_acyclic_graph(graph):
        raise ValueError("Strata are only defined for a DAG; graph has a cycle")
    stratumOf = {}
    for node in nx.topological_sort(graph):
        predStrata = [stratumOf[p] for p in graph.predecessors(node)]
        stratumOf[node] = 1 + max(predStrata) if predStrata else 0
    return stratumOf


def stratumDistribution(stratumOf):
    """Counts and percentages of nodes per stratum, as a list of dict rows."""
    counts = Counter(stratumOf.values())
    total = len(stratumOf)
    return [
        {"stratum": s, "courseCount": counts[s], "percent": 100.0 * counts[s] / total}
        for s in range(max(counts) + 1)
    ]


# ---------------------------------------------------------------------------
# Reach (forward BFS tree size)
# ---------------------------------------------------------------------------
def bfsTreeSize(graph, source):
    """Size of the BFS tree rooted at source, counting the source itself.

    Plain breadth-first search: start a queue with the source, repeatedly pop a
    course and enqueue every not-yet-seen successor (dependent course). The
    number of courses ever marked 'seen' is the BFS tree size.
    """
    seen = {source}
    queue = deque([source])
    while queue:
        current = queue.popleft()
        for nxt in graph.successors(current):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return len(seen)


def computeReach(graph):
    """Reach for every node, computed efficiently in reverse topological order.

    The descendant set of u is the union over its successors v of
    ({v} | descendants(v)). Processing nodes from sinks back to roots lets each
    set be built once from already-computed successor sets. Python int bitsets
    make the unions fast even for 5000-node graphs. Returns two dicts:
    descendantCount (excludes the source) and reach (= descendants + 1).
    """
    order = list(nx.topological_sort(graph))
    bitIndex = {node: i for i, node in enumerate(order)}
    descBits = {}
    for node in reversed(order):
        bits = 0
        for succ in graph.successors(node):
            bits |= descBits[succ] | (1 << bitIndex[succ])
        descBits[node] = bits
    descendantCount = {node: bin(bits).count("1") for node, bits in descBits.items()}
    reach = {node: c + 1 for node, c in descendantCount.items()}
    return descendantCount, reach


def topKWithTies(scoreOf, k):
    """Top-k ranking that keeps every node tied with the k-th value.

    Uses standard competition ranking (1, 2, 2, 4, ...). Returns rows sorted by
    score (desc) then label, plus a flag saying whether ties extend the list.
    """
    ordered = sorted(scoreOf.items(), key=lambda kv: (-kv[1], kv[0]))
    if not ordered:
        return []
    cutoff = ordered[min(k, len(ordered)) - 1][1]
    rows, rank = [], 0
    for position, (node, score) in enumerate(ordered, start=1):
        if score < cutoff:
            break
        if position == 1 or score != rows[-1]["score"]:
            rank = position
        rows.append({"rank": rank, "course": node, "score": score})
    tieCount = Counter(r["score"] for r in rows)
    for r in rows:
        r["tiedWith"] = tieCount[r["score"]] - 1
    return rows


# ---------------------------------------------------------------------------
# Directed path statistics (reachable ordered pairs only)
# ---------------------------------------------------------------------------
def directedPathStatistics(graph):
    """Shortest directed path statistics over reachable ordered pairs (u, v), u != v.

    BFS from every node gives the shortest-path length to each course it can
    reach. Unreachable pairs are excluded (their distance is infinite), which
    matches Gephi's 'Average Path Length' definition for directed graphs.
    """
    lengthCounts = Counter()
    for source in graph.nodes():
        for target, dist in nx.single_source_shortest_path_length(graph, source).items():
            if target != source:
                lengthCounts[dist] += 1
    reachablePairs = sum(lengthCounts.values())
    n = graph.number_of_nodes()
    totalLength = sum(d * c for d, c in lengthCounts.items())
    return {
        "reachablePairs": reachablePairs,
        "reachablePairFraction": reachablePairs / (n * (n - 1)) if n > 1 else 0.0,
        "avgShortestPathLength": totalLength / reachablePairs if reachablePairs else 0.0,
        "diameterReachable": max(lengthCounts) if lengthCounts else 0,
        "pathLengthCounts": dict(sorted(lengthCounts.items())),
    }


# ---------------------------------------------------------------------------
# Program subgraph extraction
# ---------------------------------------------------------------------------
def departmentNodes(graph, deptCodes):
    """All nodes whose label contains a course from any of deptCodes."""
    wanted = set(deptCodes)
    return {n for n in graph.nodes() if wanted.intersection(courseDepartments(n))}


def extractProgramGraph(graph, deptCodes):
    """Department courses + all of their transitive prerequisites (induced subgraph).

    Prerequisites of course X are exactly the nodes that can reach X, i.e. the
    BFS tree of X in the REVERSED (transposed) graph. We run one multi-source
    BFS on graph.reverse() seeded with every department course, take the union
    of everything reached, and return the induced subgraph on that node set.
    Department courses with no prerequisites and no dependents (isolated) are
    still seeds, so they are kept.
    """
    seeds = departmentNodes(graph, deptCodes)
    reversedView = graph.reverse(copy=False)
    keep = set(seeds)
    queue = deque(seeds)
    while queue:
        current = queue.popleft()
        for prereq in reversedView.successors(current):   # = graph.predecessors
            if prereq not in keep:
                keep.add(prereq)
                queue.append(prereq)
    subgraph = graph.subgraph(keep).copy()
    for node in subgraph.nodes():
        subgraph.nodes[node]["isTargetDept"] = int(node in seeds)
    return subgraph, seeds


# ---------------------------------------------------------------------------
# Weak components
# ---------------------------------------------------------------------------
def weakComponentSummary(graph):
    """Sizes of weakly connected components (ignoring edge direction)."""
    components = sorted(nx.weakly_connected_components(graph), key=len, reverse=True)
    sizes = [len(c) for c in components]
    return components, {
        "weakComponents": len(components),
        "largestComponentSize": sizes[0] if sizes else 0,
        "largestComponentPercent": 100.0 * sizes[0] / graph.number_of_nodes() if sizes else 0.0,
        "singletonComponents": sum(1 for s in sizes if s == 1),
        "intermediateComponents": sum(1 for s in sizes[1:] if s > 1),
    }
