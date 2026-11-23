"""
config.py - Central configuration for the Project 2 CPN analysis.

Everything that is a *choice* (which input files, which department codes make up
each program, where outputs go, algorithm parameters) lives here so it can be
changed in one place and re-run.
"""
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths (relative to the project2-cpn-at-scale folder, one level above this
# file). DATA_DIR and RESULTS_DIR override the input and output folders.
# ---------------------------------------------------------------------------
projectRoot = Path(__file__).resolve().parent.parent
repoRoot = projectRoot.parent

inputDir = Path(os.environ.get("DATA_DIR", projectRoot / "data"))  # the five institutional GML files
resultsDir = Path(os.environ.get("RESULTS_DIR", projectRoot / "results"))
tablesDir = resultsDir / "tables"
institutionTablesDir = tablesDir / "institutions"   # Part B whole-CPN tables
programTablesDir = tablesDir / "programs"            # Part B program-subgraph tables
gephiTablesDir = tablesDir / "gephi"                 # Part A/C tables computed by Gephi
extractedGraphDir = resultsDir / "graphs"            # the 15 program GML files
networkxFigureDir = resultsDir / "figures" / "networkx"
gephiFigureDir = resultsDir / "figures" / "gephi"
gephiProjectDir = resultsDir / "gephi"
statisticsDir = resultsDir / "statistics"            # Gephi statistics reports

# Project 1 SIUE program graphs (used only for the Part C consistency check).
# Default: the GML files written by project1-cpn-exploration/src/cpn_analysis.py.
# Override with: python src/compareProject1.py --project1-dir PATH
project1Dir = repoRoot / "project1-cpn-exploration" / "results" / "gml"

# ---------------------------------------------------------------------------
# Institutions. Order here is the order used in every table and chart.
# File names are looked up in inputDir (see data/README.md).
# ---------------------------------------------------------------------------
institutionFiles = {
    "SIUE": "siue.gml",
    "SIUC": "siuc.gml",
    "UIUC": "uiuc.gml",
    "MST": "mst.gml",      # Missouri S&T
    "UMKC": "umkc.gml",
}

# ---------------------------------------------------------------------------
# Program -> department-code mappings (CONFIGURABLE).
# A node belongs to a program if ANY course code in its label (labels of
# cross-listed courses look like "CS374/ECE374") starts with one of these
# department codes followed directly by the course number.
#
# Mapping decisions (see README "Department mapping decisions"):
#  * UIUC has no BIOL code. Biology is split between IB (Integrative Biology)
#    and MCB (Molecular & Cellular Biology) -> both are used.
#  * MST's Electrical & Computer Engineering department uses two codes,
#    ELECENG and COMPENG. Every other institution teaches computer engineering
#    under its single ECE-style code, so COMPENG is included for comparability.
#    The ELECENG-only variant is reported as a sensitivity check.
#  * SIUE/SIUC "CE" is Civil Engineering, not Computer Engineering -> excluded.
#  * SIUC also has ZOOL, PLB, MICR biology codes; the primary mapping uses BIOL
#    only (as given), and a broader variant is reported as a sensitivity check.
# ---------------------------------------------------------------------------
programMappings = {
    "SIUE": {"CS": ["CS"], "ECE": ["ECE"], "BIOL": ["BIOL"]},
    "SIUC": {"CS": ["CS"], "ECE": ["ECE"], "BIOL": ["BIOL"]},
    "UIUC": {"CS": ["CS"], "ECE": ["ECE"], "BIOL": ["IB", "MCB"]},
    "MST": {"CS": ["COMPSCI"], "ECE": ["ELECENG", "COMPENG"], "BIOL": ["BIOSCI"]},
    "UMKC": {"CS": ["COMPSCI"], "ECE": ["ECENGR"], "BIOL": ["BIOLOGY"]},
}

# Alternative mappings that are only summarised (not exported as the 15 GMLs).
sensitivityMappings = {
    ("MST", "ECE"): ["ELECENG"],
    ("SIUC", "BIOL"): ["BIOL", "ZOOL", "PLB", "MICR"],
}

programOrder = ["CS", "ECE", "BIOL"]

# ---------------------------------------------------------------------------
# Algorithm parameters
# ---------------------------------------------------------------------------
pageRankAlpha = 0.85          # damping factor (same as Gephi's default p = 0.85)
topK = 5                      # size of the reach rankings
deepStratumThreshold = 3      # "deeper strata" = stratum >= 3 (chains of >= 4 courses)
exactBetweenness = True       # graphs are small enough (<= 5126 nodes) for exact Brandes
modularityResolutions = [0.5, 1.0, 1.5]
