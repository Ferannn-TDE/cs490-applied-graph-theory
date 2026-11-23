# Project 1: Exploring course prerequisite networks

Builds course prerequisite networks (CPNs) for five SIUE degree programs — Biology (BIOL),
Computer Science (CS), Electrical and Computer Engineering (ECE), Mathematics (MATH) and
Mechanical Engineering (ME) — and measures program depth and course importance with NetworkX.
The exported GML files were explored in Gephi.

## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Place the five input CSVs in `data/` (see [data/README.md](data/README.md)).

## Commands

Run from this folder:

| Command | What it does | Measured runtime |
|---|---|---|
| `.venv/bin/python src/network_analysis.py` | Builds all five graphs and writes four CSV tables to `results/` | 0.2 s |
| `.venv/bin/python src/cpn_analysis.py [PROGRAM ...]` | Writes `results/gml/<PROGRAM>.gml` for Gephi (default: all five) | 0.1 s |

`DATA_DIR` and `RESULTS_DIR` override the input and output folders. Project 2's consistency
check reads the GML files from `results/gml/`.

## Outputs

| File | Contents | In the repo? |
|---|---|---|
| `results/program_summary.csv` | Nodes, edges, depth, strata, reach statistics and one longest chain per program | Yes |
| `results/top5_comparison.csv` | Top five courses by reach and by betweenness per program | Yes |
| `results/course_metrics.csv` | Reach, betweenness and stratum for every course | No (per-course listing of the input data) |
| `results/topological_strata.csv` | Every course listed by stratum | No (same reason) |
| `results/gml/*.gml` | Graphs for Gephi | No (derived from the input data) |

## Method

- Each CSV row is `course, prereq1, prereq2, ...`, so the raw graph points from a course to
  its prerequisites. The graph is **transposed** so edges run prerequisite → dependent course;
  paths then follow the order in which courses are taken.
- **Depth** is the longest path in edges; **strata** are topological generations (stratum 0 has
  no prerequisites), so the number of strata is depth + 1.
- **Reach** is the number of courses downstream of a course (descendants, excluding itself).
- **Betweenness** is directed, unweighted and normalized.
- Every graph is checked to be a DAG before analysis.

## Key results

| Program | Courses | Edges | Longest chain (courses) | Highest reach | Highest betweenness |
|---|---:|---:|---:|---|---|
| BIOL | 78 | 108 | 10 | MATH120 (70) | BIOL220 |
| CS | 33 | 49 | 9 | MATH120 (30) | CS150 |
| ECE | 56 | 86 | 12 | MATH120 (54) | ECE211 |
| MATH | 35 | 60 | 8 | MATH120 (32) | MATH150 |
| ME | 49 | 71 | 11 | MATH120 (44) | CE240 |

- **Introductory math gates everything.** MATH120 has the highest reach in all five programs.
- **Reach and betweenness disagree.** Reach rewards early courses that many others depend on;
  betweenness rewards mid-chain "bridge" courses (CS150, ECE211, CE240) and is zero for sources.
- **ECE is deepest** (11 edges, 12 courses in its longest chain). **CS has the highest mean
  reach relative to its size** (each course leads to about 21% of the others on average).
- Many courses are terminal: 12 of 33 in CS and 44 of 78 in BIOL have no dependents.

Source: `results/program_summary.csv`, `results/top5_comparison.csv`.
