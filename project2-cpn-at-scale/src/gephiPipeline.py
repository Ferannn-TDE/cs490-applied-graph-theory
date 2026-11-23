"""
gephiPipeline.py - Parts A and C run with the REAL Gephi 0.11.3 engine, headless.

How this works
--------------
Gephi is a Java application built from modules (the "Gephi Toolkit" is these
same modules packaged as a library). The installed Gephi.app (GEPHI_HOME)
ships the module jars and a Java 17 runtime. JPype starts that JVM inside
Python and calls Gephi's own classes: the GML importer, the statistics
plugins (Degree, GraphDistance, PageRank, ConnectedComponents, Modularity),
the ForceAtlas2 / Yifan Hu layouts, the Appearance module, the Preview PDF
exporter, the spreadsheet (Data Laboratory) exporter and the .gephi project
writer. Every number and file this script produces therefore comes from Gephi,
not from NetworkX.

What it CANNOT do: drive the Gephi GUI. GUI screenshots of the Statistics
panel are not produced; instead Gephi's own HTML statistics reports (the
content of the report window the GUI opens) are saved and rendered to PNG.

Environment variables:
    GEPHI_HOME   path to Gephi.app (default: /Applications/Gephi.app)
    CHROME_PATH  Chrome binary used to render the HTML reports to PNG
                 (default: /Applications/Google Chrome.app/Contents/MacOS/Google Chrome;
                 PNG rendering is skipped if it does not exist)

Run from the project2-cpn-at-scale folder:
    .venv/bin/python src/gephiPipeline.py            # Part A + Part C
    .venv/bin/python src/gephiPipeline.py --partA    # institutions only
    .venv/bin/python src/gephiPipeline.py --partC    # program graphs only
"""
import argparse
import csv
import glob
import json
import os
import re
import shutil
import subprocess
import time
from collections import Counter, defaultdict
from pathlib import Path

import jpype
import jpype.imports

import config
from cpnCommon import courseDepartments, rankedCounts

gephiApp = Path(os.environ.get("GEPHI_HOME", "/Applications/Gephi.app"))
gephiModuleRoot = gephiApp / "Contents/Resources/gephi"
gephiJvm = gephiApp / "Contents/PlugIns/jdk-17.0.20.1+1-jre/Contents/Home/lib/server/libjvm.dylib"
chromeBinary = Path(os.environ.get("CHROME_PATH", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))

# Reference categorical palette (slots 1-8) + neutral gray for "Other".
paletteHex = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
otherHex = "#bdbcb6"

# ---------------------------------------------------------------------------
# Recorded layout settings (written to results/tables/gephi/*layout_settings.csv)
# ---------------------------------------------------------------------------
forceAtlas2Settings = {
    "layout": "ForceAtlas2", "seed": 490, "threads": 1,
    "scalingRatio": 2.0, "gravity": 1.0, "strongGravityMode": False,
    "linLogMode": False, "outboundAttractionDistribution": False,
    "barnesHutOptimize": True, "barnesHutTheta": 1.2, "jitterTolerance": 1.0,
    "edgeWeightInfluence": 1.0,
    "phase1Iterations": 1500, "phase2PreventOverlapIterations": 200,
}
# LCC layout: LinLog mode separates densely linked groups more clearly.
lccForceAtlas2Settings = dict(forceAtlas2Settings, linLogMode=True, scalingRatio=1.0)
# Program graphs: strong gravity keeps isolated department courses near the core.
programForceAtlas2Settings = dict(forceAtlas2Settings, strongGravityMode=True, gravity=1.0,
                                  scalingRatio=60.0, phase1Iterations=1000,
                                  phase2PreventOverlapIterations=300)
yifanHuSettings = {
    "layout": "Yifan Hu", "optimalDistance": 100.0, "relativeStrength": 0.2,
    "initialStep": 20.0, "stepRatio": 0.95, "adaptiveCooling": True,
    "convergenceThreshold": 1e-4, "quadTreeMaxLevel": 10, "barnesHutTheta": 1.2,
    "maxIterations": 3000,
}
programYifanHuSettings = dict(yifanHuSettings, optimalDistance=40.0)
modularityRepeats = 10      # extra runs per resolution to measure run-to-run variation


def startGephi():
    """Start the JVM bundled with Gephi.app with every Gephi module jar on the classpath."""
    jars = [j for j in glob.glob(str(gephiModuleRoot / "**/*.jar"), recursive=True) if "/locale/" not in j]
    jpype.startJVM(str(gephiJvm), "-Djava.awt.headless=true", "-Xmx6g",
                   "--add-opens=java.base/java.net=ALL-UNNAMED", classpath=jars)


class GephiSession:
    """Thin wrapper around the Gephi controllers we need."""

    def __init__(self):
        from org.openide.util import Lookup
        from org.gephi.project.api import ProjectController
        from org.gephi.io.importer.api import ImportController
        from org.gephi.graph.api import GraphController
        from org.gephi.appearance.api import AppearanceController
        from org.gephi.preview.api import PreviewController
        from org.gephi.io.exporter.api import ExportController
        lookup = Lookup.getDefault()
        self.projectController = lookup.lookup(ProjectController)
        self.importController = lookup.lookup(ImportController)
        self.graphController = lookup.lookup(GraphController)
        self.appearanceController = lookup.lookup(AppearanceController)
        self.previewController = lookup.lookup(PreviewController)
        self.exportController = lookup.lookup(ExportController)

    # -- project / import --------------------------------------------------
    def newProject(self):
        if self.projectController.getCurrentProject() is not None:
            self.projectController.closeCurrentProject()
        self.projectController.newProject()
        return self.projectController.getCurrentProject()

    def importDirected(self, gmlPath, workspaceName):
        """Import a GML file into a NEW workspace with edges forced to directed."""
        from java.io import File
        from org.gephi.io.importer.api import EdgeDirectionDefault
        from org.gephi.io.processor.plugin import DefaultProcessor
        project = self.projectController.getCurrentProject()
        workspace = self.projectController.newWorkspace(project)
        self.projectController.renameWorkspace(workspace, workspaceName)
        self.projectController.openWorkspace(workspace)
        container = self.importController.importFile(File(str(gmlPath)))
        container.getLoader().setEdgeDefault(EdgeDirectionDefault.DIRECTED)
        self.importController.process(container, DefaultProcessor(), workspace)
        graphModel = self.graphController.getGraphModel(workspace)
        return workspace, graphModel

    def saveProject(self, path):
        from java.io import File
        path.parent.mkdir(parents=True, exist_ok=True)
        # newProject() creates an empty default workspace; drop it so the saved
        # project only contains the analysis workspaces.
        project = self.projectController.getCurrentProject()
        for workspace in list(project.getWorkspaces()):
            if self.graphController.getGraphModel(workspace).getGraph().getNodeCount() == 0:
                self.projectController.deleteWorkspace(workspace)
        self.projectController.saveProject(self.projectController.getCurrentProject(), File(str(path)))


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def runCentralityStatistics(graphModel, reportDir, prefix):
    """Gephi Degree, directed GraphDistance (betweenness/closeness/diameter/avg path),
    directed PageRank and ConnectedComponents (weak + strong). Returns a summary."""
    from org.gephi.statistics.plugin import Degree, GraphDistance, PageRank, ConnectedComponents
    summary = {}
    degree = Degree()
    degree.execute(graphModel)
    summary["avgDegree"] = degree.getAverageDegree()
    saveReport(degree.getReport(), reportDir, f"{prefix}_Degree")

    distance = GraphDistance()
    distance.setDirected(True)
    distance.setNormalized(False)          # raw betweenness, comparable with NetworkX normalized=False
    distance.execute(graphModel)
    summary["diameter"] = distance.getDiameter()
    summary["radius"] = distance.getRadius()
    summary["avgPathLength"] = distance.getPathLength()
    saveReport(distance.getReport(), reportDir, f"{prefix}_GraphDistance")

    pageRank = PageRank()
    pageRank.setDirected(True)
    pageRank.setProbability(config.pageRankAlpha)
    pageRank.setEpsilon(0.001)
    pageRank.setUseEdgeWeight(False)
    pageRank.execute(graphModel)
    saveReport(pageRank.getReport(), reportDir, f"{prefix}_PageRank")

    components = ConnectedComponents()
    components.setDirected(True)           # computes weakly AND strongly connected components
    components.execute(graphModel)
    summary["weakComponents"] = components.getConnectedComponentsCount()
    sizes = list(components.getComponentsSize())
    summary["giantComponentIndex"] = components.getGiantComponent()
    summary["giantComponentSize"] = max(sizes) if sizes else 0
    saveReport(components.getReport(), reportDir, f"{prefix}_ConnectedComponents")
    graph = graphModel.getDirectedGraph()
    summary["nodes"] = graph.getNodeCount()
    summary["edges"] = graph.getEdgeCount()
    summary["isDirected"] = bool(graphModel.isDirected())
    return summary


def saveReport(html, reportDir, name):
    """Save a Gephi statistics HTML report with its chart images copied alongside,
    then render it to PNG with headless Chrome (an image of Gephi's report, NOT a
    GUI screenshot)."""
    reportDir.mkdir(parents=True, exist_ok=True)
    html = str(html)
    for k, src in enumerate(re.findall(r'SRC="file:([^"]+)"', html, flags=re.I)):
        imgName = f"{name}_chart{k}.png"
        try:
            shutil.copy(src, reportDir / imgName)
            html = html.replace(f"file:{src}", imgName)
        except OSError:
            pass
    htmlPath = reportDir / f"{name}.html"
    htmlPath.write_text(html)
    if chromeBinary.exists():
        subprocess.run([str(chromeBinary), "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        f"--screenshot={reportDir / (name + '_report.png')}", "--window-size=900,2600",
                        htmlPath.resolve().as_uri()],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)


# ---------------------------------------------------------------------------
# Layouts
# ---------------------------------------------------------------------------
def runForceAtlas2(graphModel, settings=forceAtlas2Settings):
    """ForceAtlas2: repulsion between all nodes (Barnes-Hut approximated), attraction
    along edges, gravity toward the centre. Phase 2 turns on 'prevent overlap'."""
    from org.gephi.layout.plugin.forceAtlas2 import ForceAtlas2Builder
    from java.lang import Double, Boolean, Integer
    layout = ForceAtlas2Builder().buildLayout()
    layout.setGraphModel(graphModel)
    layout.resetPropertiesValues()
    layout.setInitialisationSeed(settings["seed"])
    layout.setThreadsCount(Integer(settings["threads"]))
    layout.setScalingRatio(Double(settings["scalingRatio"]))
    layout.setGravity(Double(settings["gravity"]))
    layout.setStrongGravityMode(Boolean(settings["strongGravityMode"]))
    layout.setLinLogMode(Boolean(settings["linLogMode"]))
    layout.setOutboundAttractionDistribution(Boolean(settings["outboundAttractionDistribution"]))
    layout.setBarnesHutOptimize(Boolean(settings["barnesHutOptimize"]))
    layout.setBarnesHutTheta(Double(settings["barnesHutTheta"]))
    layout.setJitterTolerance(Double(settings["jitterTolerance"]))
    layout.setEdgeWeightInfluence(Double(settings["edgeWeightInfluence"]))
    layout.setAdjustSizes(Boolean(False))
    layout.initAlgo()
    for _ in range(settings["phase1Iterations"]):
        layout.goAlgo()
    layout.setAdjustSizes(Boolean(True))     # "Prevent Overlap"
    for _ in range(settings["phase2PreventOverlapIterations"]):
        layout.goAlgo()
    layout.endAlgo()


def runYifanHu(graphModel, settings=yifanHuSettings):
    """Yifan Hu: force-directed layout with adaptive step cooling; stops on convergence."""
    from org.gephi.layout.plugin.force.yifanHu import YifanHu
    from java.lang import Float, Boolean, Integer
    layout = YifanHu().buildLayout()
    layout.setGraphModel(graphModel)
    layout.resetPropertiesValues()
    layout.setOptimalDistance(Float(settings["optimalDistance"]))
    layout.setRelativeStrength(Float(settings["relativeStrength"]))
    layout.setInitialStep(Float(settings["initialStep"]))
    layout.setStepRatio(Float(settings["stepRatio"]))
    layout.setAdaptiveCooling(Boolean(settings["adaptiveCooling"]))
    layout.setConvergenceThreshold(Float(settings["convergenceThreshold"]))
    layout.setQuadTreeMaxLevel(Integer(settings["quadTreeMaxLevel"]))
    layout.setBarnesHutTheta(Float(settings["barnesHutTheta"]))
    layout.initAlgo()
    iterations = 0
    while layout.canAlgo() and iterations < settings["maxIterations"]:
        layout.goAlgo()
        iterations += 1
    layout.endAlgo()
    return iterations


# ---------------------------------------------------------------------------
# Appearance (node size by betweenness, colour by partition) and Preview export
# ---------------------------------------------------------------------------
def hexToColor(hexValue):
    from java.awt import Color
    return Color(int(hexValue[1:3], 16), int(hexValue[3:5], 16), int(hexValue[5:7], 16))


def addColorGroupColumn(graphModel, columnName, groupOf):
    """Add a string node column used for partition colouring (groupOf: label -> group)."""
    from java.lang import String
    table = graphModel.getNodeTable()
    if not table.hasColumn(columnName):
        table.addColumn(columnName, String)
    for node in graphModel.getGraph().getNodes().toArray():
        node.setAttribute(columnName, String(groupOf(str(node.getLabel()))))


def layoutExtent(graphModel):
    """Width of the layout's bounding box (node sizes are scaled relative to it so
    that layouts with different coordinate ranges render comparably)."""
    xs, ys = [], []
    for node in graphModel.getGraph().getNodes().toArray():
        xs.append(node.x())
        ys.append(node.y())
    return max(max(xs) - min(xs), max(ys) - min(ys), 1.0)


def applyAppearance(session, workspace, graphModel, partitionColumn, colorOfGroup,
                    sizeColumn="betweenesscentrality", minFraction=0.002, maxFraction=0.025,
                    absoluteSizes=None):
    """Gephi Appearance: Ranking -> node size by betweenness; Partition -> node colour.

    Node size range = [minFraction, maxFraction] x layout width (recorded in the
    layout-settings table), so small and large layouts are equally legible."""
    if absoluteSizes:                       # fixed (min, max) sizes, used before a layout runs
        minSize, maxSize = absoluteSizes
    else:
        extent = layoutExtent(graphModel)
        minSize, maxSize = minFraction * extent, maxFraction * extent
    from org.gephi.appearance.plugin import RankingNodeSizeTransformer, PartitionElementColorTransformer
    model = session.appearanceController.getModel(workspace)
    table = graphModel.getNodeTable()
    # Size by betweenness (Gephi's column id keeps Gephi's own spelling "betweenesscentrality")
    sizeFunction = model.getNodeFunction(table.getColumn(sizeColumn), RankingNodeSizeTransformer)
    transformer = sizeFunction.getTransformer()
    transformer.setMinSize(float(minSize))
    transformer.setMaxSize(float(maxSize))
    session.appearanceController.transform(sizeFunction)
    # Colour by partition
    column = table.getColumn(partitionColumn)
    partition = model.getNodePartition(column)
    graph = graphModel.getGraph()
    for value in partition.getValues(graph):
        partition.setColor(value, hexToColor(colorOfGroup(str(value))))
    colorFunction = model.getNodeFunction(column, PartitionElementColorTransformer)
    session.appearanceController.transform(colorFunction)


def exportPdf(session, workspace, pdfPath, showLabels=False, labelSize=4):
    """Preview settings + Gephi's PDF exporter."""
    from java.awt import Color, Font
    from java.lang import Boolean, Float
    from java.io import File
    from org.gephi.preview.api import PreviewProperty
    from org.gephi.preview.types import EdgeColor
    from org.gephi.io.exporter.preview import PDFExporter
    props = session.previewController.getModel(workspace).getProperties()
    props.putValue(PreviewProperty.SHOW_NODE_LABELS, Boolean(showLabels))
    props.putValue(PreviewProperty.NODE_LABEL_FONT, Font("Arial", Font.PLAIN, labelSize))
    props.putValue(PreviewProperty.NODE_LABEL_PROPORTIONAL_SIZE, Boolean(False))
    props.putValue(PreviewProperty.NODE_BORDER_WIDTH, Float(0.0))
    props.putValue(PreviewProperty.EDGE_CURVED, Boolean(False))
    props.putValue(PreviewProperty.EDGE_THICKNESS, Float(0.3 if not showLabels else 0.8))
    props.putValue(PreviewProperty.EDGE_OPACITY, Float(35.0 if not showLabels else 70.0))
    props.putValue(PreviewProperty.EDGE_COLOR, EdgeColor(Color(150, 150, 150)))
    props.putValue(PreviewProperty.ARROW_SIZE, Float(2.0 if not showLabels else 4.0))
    session.previewController.refreshPreview(workspace)
    exporter = PDFExporter()
    exporter.setWorkspace(workspace)
    pdfPath.parent.mkdir(parents=True, exist_ok=True)
    session.exportController.exportFile(File(str(pdfPath)), exporter)


def exportNodeTable(session, workspace, csvPath):
    """Gephi spreadsheet exporter = Data Laboratory 'Export table' for the node table."""
    from java.io import File
    from org.gephi.io.exporter.plugin import ExporterSpreadsheet
    exporter = ExporterSpreadsheet()
    exporter.setWorkspace(workspace)
    exporter.setTableToExport(ExporterSpreadsheet.ExportTable.NODES)
    exporter.setFieldDelimiter(",")
    csvPath.parent.mkdir(parents=True, exist_ok=True)
    session.exportController.exportFile(File(str(csvPath)), exporter)


def topGroupColorMap(labels, groupOfLabel, k=8):
    """Assign palette slots to the k largest groups (fixed order by size); rest = Other."""
    counts = Counter(groupOfLabel(l) for l in labels)
    counts.pop("MERGED", None)
    top = [g for g, _ in counts.most_common(k)]
    colors = {g: paletteHex[i] for i, g in enumerate(top)}
    return colors


def nodeLabels(graphModel):
    return [str(n.getLabel()) for n in graphModel.getGraph().getNodes().toArray()]


def deptOfLabel(graphModel):
    """label -> attr1 department (from the GML) as stored by Gephi."""
    table = graphModel.getNodeTable()
    attrCol = table.getColumn("attr1")
    return {str(n.getLabel()): str(n.getAttribute(attrCol)) for n in graphModel.getGraph().getNodes().toArray()}


def writeCsv(path, rows, fieldNames=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    if not rows:
        return
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldNames or list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Part A: institutional graphs
# ---------------------------------------------------------------------------
def runPartA(session):
    from java.lang import Integer
    from org.gephi.statistics.plugin import Modularity
    statRows, layoutRows, modularityRows, communityRows, componentRows = [], [], [], [], []
    stabilityRows = []
    for inst, fileName in config.institutionFiles.items():
        t0 = time.time()
        gmlPath = config.inputDir / fileName
        reportDir = config.statisticsDir / "institutions" / inst
        session.newProject()

        # ---- Workspace 1: full graph, ForceAtlas2 ------------------------------
        ws1, gm1 = session.importDirected(gmlPath, f"{inst} full - ForceAtlas2")
        stats = runCentralityStatistics(gm1, reportDir, f"{inst}_full")
        stats.update({"institution": inst, "graph": "full"})
        statRows.append(stats)
        exportNodeTable(session, ws1, config.gephiTablesDir / "institutions" / f"{inst}_gephi_nodes.csv")

        # Weak component composition from Gephi's componentnumber column
        compCol = gm1.getNodeTable().getColumn("componentnumber")
        members = defaultdict(list)
        for node in gm1.getGraph().getNodes().toArray():
            members[int(node.getAttribute(compCol))].append(str(node.getLabel()))
        ordered = sorted(members.items(), key=lambda kv: -len(kv[1]))
        for rank, (compId, labels) in enumerate(ordered, start=1):
            if rank == 1 or len(labels) == 1:
                continue
            deptCounts = Counter(d for l in labels for d in courseDepartments(l))
            componentRows.append({"institution": inst, "gephiComponentId": compId, "sizeRank": rank,
                                  "size": len(labels),
                                  "deptComposition": "; ".join(f"{d}:{c}" for d, c in rankedCounts(deptCounts)),
                                  "exampleCourses": "; ".join(sorted(labels)[:8])})

        deptOf = deptOfLabel(gm1)
        deptColors = topGroupColorMap(deptOf.keys(), lambda l: deptOf[l])
        groupOf = lambda l: deptOf[l] if deptOf[l] in deptColors else "Other"
        addColorGroupColumn(gm1, "deptColorGroup", groupOf)
        runForceAtlas2(gm1)
        applyAppearance(session, ws1, gm1, "deptColorGroup", lambda g: deptColors.get(g, otherHex),
                        minFraction=0.0015, maxFraction=0.02)
        exportPdf(session, ws1, config.gephiFigureDir / "institutions" / f"{inst}_full_ForceAtlas2.pdf")
        layoutRows.append({"institution": inst, "graph": "full", "workspace": f"{inst} full - ForceAtlas2",
                           "settings": json.dumps(forceAtlas2Settings),
                           "colouring": "Partition by attr1: 8 largest departments " +
                                        json.dumps(deptColors) + "; others/MERGED gray",
                           "nodeSize": "Ranking by betweenesscentrality, 0.15%-2% of layout width"})

        # ---- Workspace 2: full graph, Yifan Hu --------------------------------
        ws2, gm2 = session.importDirected(gmlPath, f"{inst} full - Yifan Hu")
        runCentralityStatistics(gm2, reportDir / "yifanhu_workspace", f"{inst}_full")
        addColorGroupColumn(gm2, "deptColorGroup", groupOf)
        iterations = runYifanHu(gm2)
        applyAppearance(session, ws2, gm2, "deptColorGroup", lambda g: deptColors.get(g, otherHex),
                        minFraction=0.0015, maxFraction=0.02)
        exportPdf(session, ws2, config.gephiFigureDir / "institutions" / f"{inst}_full_YifanHu.pdf")
        layoutRows.append({"institution": inst, "graph": "full", "workspace": f"{inst} full - Yifan Hu",
                           "settings": json.dumps({**yifanHuSettings, "iterationsRun": iterations}),
                           "colouring": "same department partition as ForceAtlas2",
                           "nodeSize": "Ranking by betweenesscentrality, 0.15%-2% of layout width"})

        # ---- Workspace 3: largest weakly connected component + modularity --------
        ws3, gm3 = session.importDirected(gmlPath, f"{inst} LCC - modularity")
        from org.gephi.statistics.plugin import ConnectedComponents
        cc = ConnectedComponents()
        cc.setDirected(True)
        cc.execute(gm3)
        giant = cc.getGiantComponent()
        compCol3 = gm3.getNodeTable().getColumn("componentnumber")
        graph3 = gm3.getGraph()
        outside = [n for n in graph3.getNodes().toArray() if int(n.getAttribute(compCol3)) != giant]
        graph3.removeAllNodes(java_list(outside))     # keep only the giant (largest weak) component
        lccStats = runCentralityStatistics(gm3, reportDir / "lcc", f"{inst}_LCC")
        lccStats.update({"institution": inst, "graph": "largest weak component"})
        statRows.append(lccStats)
        lccDeptOf = deptOfLabel(gm3)

        table3 = gm3.getNodeTable()
        nodeOf = {str(n.getLabel()): n for n in gm3.getGraph().getNodes().toArray()}
        for resolution in config.modularityResolutions:
            modularity, timedOut = runModularity(gm3, resolution)
            for attempt in range(3):           # retry a non-converging run (recorded below)
                if not timedOut:
                    break
                modularity, timedOut = runModularity(gm3, resolution)
            if timedOut:
                raise RuntimeError(f"{inst}: modularity at resolution {resolution} did not converge in 4 attempts")
            saveReport(modularity.getReport(), reportDir / "lcc", f"{inst}_LCC_Modularity_res{resolution}")
            # Preserve this run's membership before the next run overwrites modularity_class
            keepName = f"modClass_res{str(resolution).replace('.', '_')}"
            if not table3.hasColumn(keepName):
                table3.addColumn(keepName, Integer)
            classCol = table3.getColumn("modularity_class")
            membership = defaultdict(list)
            for node in gm3.getGraph().getNodes().toArray():
                value = int(node.getAttribute(classCol))
                node.setAttribute(keepName, Integer(value))
                membership[value].append(str(node.getLabel()))
            sizes = sorted((len(v) for v in membership.values()), reverse=True)
            lccSize = sum(sizes)
            # Department purity: share of courses that sit in a community whose most
            # common department is their own department (higher = cleaner grouping).
            pure = 0
            for value, labels in membership.items():
                pure += Counter(lccDeptOf[l] for l in labels).most_common(1)[0][1]
            modularityRows.append({
                "institution": inst, "resolution": resolution, "randomize": False, "useWeights": False,
                "timedOutAttemptsBeforeSuccess": attempt,
                "edgesTreatedAs": "undirected (Gephi Modularity uses the undirected view)",
                "modularityQ": modularity.getModularity(),
                "communities": len(sizes), "lccNodes": lccSize,
                "largestCommunity": sizes[0], "largestCommunityPercent": 100.0 * sizes[0] / lccSize,
                "communitiesWith10Plus": sum(1 for s in sizes if s >= 10),
                "medianCommunitySize": sizes[len(sizes) // 2],
                "deptPurity": pure / lccSize,
            })
            for value, labels in sorted(membership.items(), key=lambda kv: -len(kv[1])):
                deptCounts = Counter(d for l in labels for d in courseDepartments(l))
                hubs = sorted(labels, key=lambda l: (-gm3.getGraph().getDegree(nodeOf[l]), l))[:6]
                communityRows.append({
                    "institution": inst, "resolution": resolution, "community": value,
                    "size": len(labels),
                    "topDepts": "; ".join(f"{d}:{c}" for d, c in deptCounts.most_common(6)),
                    "dominantDept": deptCounts.most_common(1)[0][0],
                    "dominantDeptShare": round(deptCounts.most_common(1)[0][1] / len(labels), 3),
                    "highestDegreeCourses": "; ".join(hubs),
                })

        # Stability: Gephi's Louvain implementation is not deterministic even with
        # "Randomize" off, so re-run each resolution several times WITHOUT touching the
        # preserved modClass_* columns, and record the spread of Q / communities / purity.
        for resolution in config.modularityResolutions:
            for repeat in range(1, modularityRepeats + 1):
                modularity, timedOut = runModularity(gm3, resolution)
                if timedOut:
                    stabilityRows.append({"institution": inst, "resolution": resolution, "repeat": repeat,
                                          "modularityQ": "", "communities": "", "deptPurity": "",
                                          "status": "timed out (cancelled after 120 s)"})
                    continue
                classCol = table3.getColumn("modularity_class")
                membership = defaultdict(list)
                for node in gm3.getGraph().getNodes().toArray():
                    membership[int(node.getAttribute(classCol))].append(str(node.getLabel()))
                pure = sum(Counter(lccDeptOf[l] for l in labels).most_common(1)[0][1]
                           for labels in membership.values())
                stabilityRows.append({"institution": inst, "resolution": resolution, "repeat": repeat,
                                      "modularityQ": modularity.getModularity(),
                                      "communities": len(membership),
                                      "deptPurity": pure / sum(len(v) for v in membership.values()),
                                      "status": "ok"})

        # One FA2 (LinLog) layout of the LCC; one PDF per resolution coloured by its communities
        runForceAtlas2(gm3, lccForceAtlas2Settings)
        for resolution in config.modularityResolutions:
            keepName = f"modClass_res{str(resolution).replace('.', '_')}"
            col = table3.getColumn(keepName)
            sizeOf = Counter(int(n.getAttribute(col)) for n in gm3.getGraph().getNodes().toArray())
            topComms = [c for c, _ in sizeOf.most_common(8)]
            groupCol = f"commColorGroup_res{str(resolution).replace('.', '_')}"
            commOf = {l: int(n.getAttribute(col)) for l, n in nodeOf.items()}
            addColorGroupColumn(gm3, groupCol, lambda l, top=topComms, commOf=commOf:
                                f"C{commOf[l]}" if commOf[l] in top else "Other")
            colorMap = {f"C{c}": paletteHex[i] for i, c in enumerate(topComms)}
            applyAppearance(session, ws3, gm3, groupCol, lambda g: colorMap.get(g, otherHex),
                            minFraction=0.002, maxFraction=0.02)
            exportPdf(session, ws3, config.gephiFigureDir / "institutions" /
                      f"{inst}_LCC_ForceAtlas2_modularity_res{resolution}.pdf")
        layoutRows.append({"institution": inst, "graph": "largest weak component",
                           "workspace": f"{inst} LCC - modularity",
                           "settings": json.dumps(lccForceAtlas2Settings),
                           "colouring": "Partition by each resolution's 8 largest communities; others gray",
                           "nodeSize": "Ranking by betweenesscentrality (LCC), 0.2%-2% of layout width"})
        exportNodeTable(session, ws3, config.gephiTablesDir / "institutions" / f"{inst}_LCC_gephi_nodes_modularity.csv")

        session.projectController.openWorkspace(ws1)
        session.saveProject(config.gephiProjectDir / "institutions" / f"{inst}.gephi")
        print(f"[Part A] {inst} done in {time.time() - t0:.0f}s")

    writeCsv(config.gephiTablesDir / "institution_gephi_statistics.csv", statRows)
    writeCsv(config.gephiTablesDir / "institution_layout_settings.csv", layoutRows)
    writeCsv(config.gephiTablesDir / "modularity_runs.csv", modularityRows)
    writeCsv(config.gephiTablesDir / "modularity_stability_repeats.csv", stabilityRows)
    writeCsv(config.gephiTablesDir / "modularity_communities.csv", communityRows)
    writeCsv(config.gephiTablesDir / "intermediate_components_gephi.csv", componentRows)


def runModularity(graphModel, resolution, timeoutSeconds=120):
    """Run Gephi Modularity (Louvain) with a watchdog.

    Gephi's Louvain loop occasionally fails to converge at non-default resolutions
    (observed on a repeat run for UMKC). The statistic runs in a worker thread; if it
    exceeds timeoutSeconds, Gephi's own cancel() is called and the run is reported
    as timed out instead of hanging the pipeline. Returns (modularity, timedOut)."""
    import threading
    from org.gephi.statistics.plugin import Modularity
    modularity = Modularity()
    modularity.setResolution(resolution)
    modularity.setUseWeight(False)
    modularity.setRandom(False)      # Gephi "Randomize" off (results still vary run to run)
    worker = threading.Thread(target=modularity.execute, args=(graphModel,), daemon=True)
    worker.start()
    worker.join(timeoutSeconds)
    if worker.is_alive():
        modularity.cancel()
        worker.join(30)
        return modularity, True
    return modularity, False


def java_list(items):
    from java.util import ArrayList
    out = ArrayList()
    for item in items:
        out.add(item)
    return out


# ---------------------------------------------------------------------------
# Part C: the 15 program graphs
# ---------------------------------------------------------------------------
def runPartC(session):
    statRows, layoutRows = [], []
    programColor = dict(zip(config.programOrder, paletteHex[:3]))
    for inst in config.institutionFiles:
        for program in config.programOrder:
            gmlPath = config.extractedGraphDir / f"{inst}_{program}.gml"
            name = f"{inst}_{program}"
            reportDir = config.statisticsDir / "programs" / name
            session.newProject()
            colorOf = lambda g, p=program: programColor[p] if g == "target" else otherHex
            for layoutName in ("ForceAtlas2", "Yifan Hu"):
                ws, gm = session.importDirected(gmlPath, f"{name} - {layoutName}")
                stats = runCentralityStatistics(gm, reportDir if layoutName == "ForceAtlas2"
                                                else reportDir / "yifanhu_workspace", name)
                targetCol = gm.getNodeTable().getColumn("isTargetDept")
                isTarget = {str(n.getLabel()): int(n.getAttribute(targetCol))
                            for n in gm.getGraph().getNodes().toArray()}
                addColorGroupColumn(gm, "programRole", lambda l: "target" if isTarget[l] else "prerequisite")
                # Size by betweenness FIRST so the layout's overlap prevention knows node sizes.
                applyAppearance(session, ws, gm, "programRole", colorOf, absoluteSizes=(4.0, 24.0))
                if layoutName == "ForceAtlas2":
                    settings = programForceAtlas2Settings
                    runForceAtlas2(gm, settings)
                    stats.update({"institution": inst, "program": program})
                    statRows.append(stats)
                    exportNodeTable(session, ws, config.gephiTablesDir / "programs" / f"{name}_gephi_nodes.csv")
                else:
                    # Yifan Hu has no gravity, so isolated courses drift to the page edges and
                    # shrink the connected structure to a dot. In this workspace ONLY, isolated
                    # nodes are removed after the statistics were computed (the equivalent of a
                    # Degree Range >= 1 filter); the ForceAtlas2 workspace keeps every node.
                    graph = gm.getGraph()
                    isolated = [n for n in graph.getNodes().toArray() if graph.getDegree(n) == 0]
                    graph.removeAllNodes(java_list(isolated))
                    settings = dict(programYifanHuSettings, isolatedNodesRemovedForThisView=len(isolated))
                    settings["iterationsRun"] = runYifanHu(gm, programYifanHuSettings)
                tag = "ForceAtlas2" if layoutName == "ForceAtlas2" else "YifanHu_isolatesRemoved"
                labelSize = max(1, round(layoutExtent(gm) / 110))   # label font scaled to layout size
                settings["labelFontSize"] = labelSize
                exportPdf(session, ws, config.gephiFigureDir / "programs" / f"{name}_{tag}.pdf",
                          showLabels=True, labelSize=labelSize)
                layoutRows.append({"institution": inst, "program": program, "workspace": f"{name} - {layoutName}",
                                   "settings": json.dumps(settings),
                                   "colouring": f"{program} dept courses {programColor[program]}; prerequisites gray",
                                   "nodeSize": "Ranking by betweenesscentrality, absolute 4-24 (applied before layout)"})
            session.saveProject(config.gephiProjectDir / "programs" / f"{name}.gephi")
            print(f"[Part C] {name}: {stats['nodes']} nodes, {stats['edges']} edges")
    writeCsv(config.gephiTablesDir / "program_gephi_statistics.csv", statRows)
    writeCsv(config.gephiTablesDir / "program_layout_settings.csv", layoutRows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--partA", action="store_true")
    parser.add_argument("--partC", action="store_true")
    args = parser.parse_args()
    runA = args.partA or not args.partC
    runC = args.partC or not args.partA
    startGephi()
    from java.lang import System
    exitCode = 0
    try:
        session = GephiSession()
        if runA:
            runPartA(session)
        if runC:
            runPartC(session)
    except Exception:
        import traceback
        traceback.print_exc()
        exitCode = 1
    # Gephi leaves non-daemon (AWT) threads alive, so the JVM must be exited explicitly.
    System.exit(exitCode)


if __name__ == "__main__":
    main()
