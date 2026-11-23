#!/bin/zsh
# Re-run the complete Project 2 pipeline from the project2-cpn-at-scale folder.
#   zsh run_all.sh
# Uses .venv/bin/python unless PYTHON is set. The Gephi step needs Gephi.app (see README).
set -e
cd "$(dirname "$0")"
PY="${PYTHON:-.venv/bin/python} -u"   # -u: unbuffered, Gephi exits the JVM directly

${=PY} src/partB_networkx.py        # Part B: strata, reach, components, 15 extractions, charts
${=PY} src/gephiPipeline.py         # Parts A + C with the Gephi 0.11.3 engine (headless)
${=PY} src/compareProject1.py       # Part C: Project 1 SIUE graphs vs. new extractions
${=PY} src/communityPatterns.py     # Part A.3: cross-institution community patterns
${=PY} src/validate.py              # all checks -> results/tables/validation_report.csv
