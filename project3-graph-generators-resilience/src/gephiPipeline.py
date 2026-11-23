"""Genuine Gephi 0.11.3 projects and Preview PDFs for the 36 structural graphs.

How it works: the installed Gephi.app (GEPHI_HOME) ships Gephi's module jars and a
Java 17 runtime. JPype starts that JVM inside Python and calls Gephi's own classes
(GML importer, Degree statistic, ForceAtlas2 layout, Appearance, Preview PDF exporter
and .gephi project writer) without opening the GUI. The technique is reused from the
Project 2 pipeline.

Set GEPHI_HOME to the Gephi.app folder if it is not /Applications/Gephi.app.

    python src/gephiPipeline.py build            # all 36 (resumes; finished graphs are skipped)
    python src/gephiPipeline.py build --only RGG_n10000_d10
    python src/gephiPipeline.py verify           # reopen every .gephi in a FRESH Gephi JVM + PDF checks

Views (workspaces) saved in each project:
  * "ForceAtlas2 comparison" - identical ForceAtlas2 settings for every model.
  * RGG only: "RGG spatial" - the generator's unit-square coordinates, uniformly scaled.
  * WS only:  "WS ring" - node i placed at angle 2*pi*i/n (NetworkX WS ring order), so
    lattice edges hug the circle and rewired shortcuts cross the interior.
Nodes are sized and shaded by degree (Gephi Degree statistic); no betweenness is computed.
"""
import argparse
import glob
import json
import math
import os
import random
import sys
import time
import zipfile
from pathlib import Path
import networkx as nx
from common import configurations, outputPath, saveJson, stableSeed, modelColors, writeCsv

gephiApp = Path(os.environ.get('GEPHI_HOME', '/Applications/Gephi.app')) / 'Contents'
gephiJvm = gephiApp / 'PlugIns/jdk-17.0.20.1+1-jre/Contents/Home/lib/server/libjvm.dylib'
gephiPath = outputPath / 'gephi'
projectPath, pdfPath, recordPath = gephiPath / 'projects', gephiPath / 'pdf', gephiPath / 'records'
graphPath = outputPath / 'structure' / 'graphs'

# Recorded view settings. Every finished layout is uniformly rescaled so its largest
# side spans viewExtent units; node sizes and edge widths are then identical across views.
viewExtent = 10000.0
forceAtlas2Settings = dict(layout='ForceAtlas2', iterations=1000, threads=7, scalingRatio=10.0, gravity=0.05,
                           strongGravityMode=True, linLogMode=False, outboundAttractionDistribution=False,
                           barnesHutOptimize=True, barnesHutTheta=1.2, jitterTolerance=1.0,
                           adjustSizes=False, initialPositions='uniform square, seed=stableSeed("gephi:"+configId)')
styleSettings = dict(nodeSize='absolute for every graph: max(3, 5*sqrt(degree)) * sqrt(10000/n) units of a 10000-unit view',
                     nodeColor='Gephi Appearance Ranking on degree within each graph: light tint -> model color',
                     nodeBorder='NODE_BORDER_WIDTH set to 0; Gephi PDF renderer still strokes a thin darker outline',
                     edgeColor='#d2d2d2', edgeThickness=0.5, edgeOpacity=100, edgeCurved=False, labels=False,
                     page='A4 portrait, Gephi PDFExporter, 10 pt margins')

def gephiFileStem(config):
    return f"{config['configId']}_seed{config['seed']}"

def startGephi(memory='-Xmx10g'):
    jars = [jar for jar in glob.glob(str(gephiApp / 'Resources/gephi/**/*.jar'), recursive=True) if '/locale/' not in jar]
    import jpype
    import jpype.imports  # noqa: F401  (enables "from org.gephi ... import ...")
    jpype.startJVM(str(gephiJvm), '-Djava.awt.headless=true', memory,
                   '--add-opens=java.base/java.net=ALL-UNNAMED', classpath=jars)
    # macOS: initialize Swing on the process main thread first. Otherwise Gephi's event thread
    # may do it during project loading and wait for this (blocked) main thread: a deadlock.
    from javax.swing import UIManager
    UIManager.getLookAndFeel()

def controllers():
    from org.openide.util import Lookup
    from org.gephi.project.api import ProjectController
    from org.gephi.io.importer.api import ImportController
    from org.gephi.graph.api import GraphController
    from org.gephi.appearance.api import AppearanceController
    from org.gephi.preview.api import PreviewController
    from org.gephi.io.exporter.api import ExportController
    lookup = Lookup.getDefault()
    return {name: lookup.lookup(cls) for name, cls in [('project', ProjectController), ('import', ImportController),
            ('graph', GraphController), ('appearance', AppearanceController), ('preview', PreviewController),
            ('export', ExportController)]}

def graphSignature(nxGraph):
    """Node-ID set and undirected edge set used to compare Gephi with the saved GML."""
    return set(nxGraph), {tuple(sorted(edge)) for edge in nxGraph.edges}

def gephiSignature(graphModel):
    graph = graphModel.getUndirectedGraph()
    nodeIds = {int(str(node.getId())) for node in graph.getNodes().toArray()}
    edgeSet = {tuple(sorted((int(str(edge.getSource().getId())), int(str(edge.getTarget().getId())))))
               for edge in graph.getEdges().toArray()}
    return nodeIds, edgeSet, graph.getNodeCount(), graph.getEdgeCount()

def importUndirected(gephi, gmlFile, workspaceName):
    """Import the GML into a new workspace with every edge forced UNDIRECTED."""
    from java.io import File
    from org.gephi.io.importer.api import EdgeDirectionDefault
    from org.gephi.io.processor.plugin import DefaultProcessor
    project = gephi['project'].getCurrentProject()
    workspace = gephi['project'].newWorkspace(project)
    gephi['project'].renameWorkspace(workspace, workspaceName)
    gephi['project'].openWorkspace(workspace)
    container = gephi['import'].importFile(File(str(gmlFile)))
    container.getLoader().setEdgeDefault(EdgeDirectionDefault.UNDIRECTED)
    gephi['import'].process(container, DefaultProcessor(), workspace)
    graphModel = gephi['graph'].getGraphModel(workspace)
    table = graphModel.getNodeTable()
    # GML "pos" is a 2-value list; Gephi keeps only its last value (y). The coordinates
    # themselves are imported from the "graphics" x/y block, so drop the misleading column.
    if table.hasColumn('pos'):
        table.removeColumn('pos')
    return workspace, graphModel

def nodeList(graphModel):
    return list(graphModel.getGraph().getNodes().toArray())

def rescaleToView(graphModel):
    """Uniform scale + translation only: shape and relative distances are unchanged."""
    nodes = nodeList(graphModel)
    xs, ys = [node.x() for node in nodes], [node.y() for node in nodes]
    centerX, centerY = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    scale = viewExtent / max(max(xs) - min(xs), max(ys) - min(ys), 1e-12)
    for node in nodes:
        node.setX(float((node.x() - centerX) * scale))
        node.setY(float((node.y() - centerY) * scale))
    return scale

def runForceAtlas2(graphModel, initSeed):
    from java.lang import Boolean, Double, Integer
    from org.gephi.layout.plugin.forceAtlas2 import ForceAtlas2Builder
    # Deterministic starting positions (Gephi's importer would otherwise randomize them).
    generator = random.Random(initSeed)
    for node in nodeList(graphModel):
        node.setX(float(generator.uniform(-viewExtent / 2, viewExtent / 2)))
        node.setY(float(generator.uniform(-viewExtent / 2, viewExtent / 2)))
    settings = forceAtlas2Settings
    layout = ForceAtlas2Builder().buildLayout()
    layout.setGraphModel(graphModel)
    layout.resetPropertiesValues()
    layout.setThreadsCount(Integer(settings['threads']))
    layout.setScalingRatio(Double(settings['scalingRatio']))
    layout.setGravity(Double(settings['gravity']))
    layout.setStrongGravityMode(Boolean(settings['strongGravityMode']))
    layout.setLinLogMode(Boolean(settings['linLogMode']))
    layout.setOutboundAttractionDistribution(Boolean(settings['outboundAttractionDistribution']))
    layout.setBarnesHutOptimize(Boolean(settings['barnesHutOptimize']))
    layout.setBarnesHutTheta(Double(settings['barnesHutTheta']))
    layout.setJitterTolerance(Double(settings['jitterTolerance']))
    layout.setAdjustSizes(Boolean(settings['adjustSizes']))
    layout.initAlgo()
    for _ in range(settings['iterations']):
        layout.goAlgo()
    layout.endAlgo()

def placeOnRing(graphModel, nodeCount):
    # watts_strogatz_graph starts from a ring lattice in node-ID order, so ID = ring position.
    for node in nodeList(graphModel):
        angle = 2 * math.pi * int(str(node.getId())) / nodeCount
        node.setX(float(math.cos(angle)))
        node.setY(float(math.sin(angle)))

def javaColor(hexValue):
    from java.awt import Color
    return Color(int(hexValue[1:3], 16), int(hexValue[3:5], 16), int(hexValue[5:7], 16))

def tint(hexValue, amount):
    """Mix a hex color with white (amount=0 keeps it, 1 gives white)."""
    channels = [int(hexValue[index:index + 2], 16) for index in (1, 3, 5)]
    return '#' + ''.join(f'{round(value + (255 - value) * amount):02x}' for value in channels)

def styleByDegree(gephi, workspace, graphModel, model):
    """Node size from one absolute degree formula (so BA hubs vs. ER/WS nodes compare fairly
    across graphs); node shade from Gephi's Appearance Ranking on the Degree column."""
    from java.awt import Color
    from jpype import JArray, JFloat
    from org.gephi.appearance.plugin import RankingElementColorTransformer
    appearanceModel = gephi['appearance'].getModel(workspace)
    degreeColumn = graphModel.getNodeTable().getColumn('degree')
    graph = graphModel.getGraph()
    densityFactor = math.sqrt(10000 / graph.getNodeCount())
    for node in graph.getNodes().toArray():
        node.setSize(float(max(3.0, 5.0 * math.sqrt(graph.getDegree(node))) * densityFactor))
    colorFunction = appearanceModel.getNodeFunction(degreeColumn, RankingElementColorTransformer)
    colorTransformer = colorFunction.getTransformer()
    colorTransformer.setColors(JArray(Color)([javaColor(tint(modelColors[model], .55)), javaColor(modelColors[model])]))
    colorTransformer.setColorPositions(JArray(JFloat)([0.0, 1.0]))
    gephi['appearance'].transform(colorFunction)

def exportPdf(gephi, workspace, targetPath):
    from java.awt import Color
    from java.io import File
    from java.lang import Boolean, Float
    from org.gephi.preview.api import PreviewProperty
    from org.gephi.preview.types import EdgeColor
    from org.gephi.io.exporter.preview import PDFExporter
    properties = gephi['preview'].getModel(workspace).getProperties()
    properties.putValue(PreviewProperty.SHOW_NODE_LABELS, Boolean(False))
    properties.putValue(PreviewProperty.NODE_BORDER_WIDTH, Float(0.0))
    properties.putValue(PreviewProperty.EDGE_CURVED, Boolean(styleSettings['edgeCurved']))
    properties.putValue(PreviewProperty.EDGE_THICKNESS, Float(styleSettings['edgeThickness']))
    properties.putValue(PreviewProperty.EDGE_OPACITY, Float(float(styleSettings['edgeOpacity'])))
    properties.putValue(PreviewProperty.EDGE_COLOR, EdgeColor(javaColor(styleSettings['edgeColor'])))
    properties.putValue(PreviewProperty.BACKGROUND_COLOR, Color.WHITE)
    gephi['preview'].refreshPreview(workspace)
    exporter = PDFExporter()
    exporter.setWorkspace(workspace)
    for setter in ['setMarginTop', 'setMarginBottom', 'setMarginLeft', 'setMarginRight']:
        getattr(exporter, setter)(Float(10.0))
    targetPath.parent.mkdir(parents=True, exist_ok=True)
    gephi['export'].exportFile(File(str(targetPath)), exporter)

def buildOne(gephi, config):
    """One project per configuration; PDFs for every view; a JSON record of what was done."""
    from java.io import File
    from org.gephi.statistics.plugin import Degree
    stem, model = gephiFileStem(config), config['model']
    gmlFile = graphPath / (config['configId'] + '.gml')
    checkpoint = json.loads((outputPath / 'structure' / 'checkpoints' / (config['configId'] + '.json')).read_text())
    expectedNodes, expectedEdges = graphSignature(nx.read_gml(gmlFile, destringizer=int))
    record = dict(configId=config['configId'], seed=config['seed'], gml=gmlFile.name, project=stem + '.gephi',
                  gephiVersion='0.11.3', forceAtlas2=forceAtlas2Settings, style=styleSettings, views=[])
    startTime = time.perf_counter()
    gephi['project'].newProject()
    defaultWorkspace = gephi['project'].getCurrentWorkspace()
    viewNames = ['ForceAtlas2 comparison'] + (['RGG spatial'] if model == 'RGG' else ['WS ring'] if model == 'WS' else [])
    for viewName in viewNames:
        viewStart = time.perf_counter()
        workspace, graphModel = importUndirected(gephi, gmlFile, viewName)
        nodeIds, edgeSet, nodeCount, edgeCount = gephiSignature(graphModel)
        # Import check: every node (isolates included) and every undirected edge, nothing extra.
        assert graphModel.isUndirected() and not graphModel.isDirected()
        assert nodeIds == expectedNodes and edgeSet == expectedEdges
        assert (nodeCount, edgeCount) == (checkpoint['actualNodes'], checkpoint['actualEdges'])
        degree = Degree()
        degree.execute(graphModel)
        assert math.isclose(degree.getAverageDegree(), checkpoint['actualAverageDegree'], rel_tol=1e-9)
        if viewName == 'ForceAtlas2 comparison':
            runForceAtlas2(graphModel, stableSeed('gephi:' + config['configId']))
            positionNote = 'ForceAtlas2 result'
        elif viewName == 'RGG spatial':
            positionNote = 'Gephi-imported GML graphics x/y (generator coordinates), uniformly scaled'
        else:
            placeOnRing(graphModel, nodeCount)
            positionNote = 'node i at angle 2*pi*i/n'
        scale = rescaleToView(graphModel)
        styleByDegree(gephi, workspace, graphModel, model)
        viewTag = viewName.split()[-1] if viewName != 'ForceAtlas2 comparison' else 'ForceAtlas2'
        pdfFile = pdfPath / f'{stem}_{viewTag}.pdf'
        exportPdf(gephi, workspace, pdfFile)
        record['views'].append(dict(workspace=viewName, pdf=pdfFile.name, positions=positionNote, uniformScale=scale,
                                    gephiNodes=nodeCount, gephiEdges=edgeCount, gephiAverageDegree=degree.getAverageDegree(),
                                    seconds=time.perf_counter() - viewStart))
        print(f'  {viewName}: {nodeCount} nodes, {edgeCount} edges, PDF {pdfFile.stat().st_size/1e6:.1f} MB '
              f'({time.perf_counter() - viewStart:.0f}s)', flush=True)
    gephi['project'].deleteWorkspace(defaultWorkspace)  # the empty workspace newProject() creates
    gephi['project'].openWorkspace(gephi['project'].getCurrentProject().getWorkspaces()[0])
    projectFile = projectPath / record['project']
    projectFile.parent.mkdir(parents=True, exist_ok=True)
    temporaryFile = projectFile.with_suffix('.gephi.tmp')
    gephi['project'].saveProject(gephi['project'].getCurrentProject(), File(str(temporaryFile)))
    temporaryFile.replace(projectFile)
    gephi['project'].closeCurrentProject()
    record.update(complete=True, totalSeconds=time.perf_counter() - startTime)
    saveJson(recordPath / (config['configId'] + '.json'), record)

def build(onlyId=None):
    startGephi()
    from java.lang import System
    exitCode = 0
    try:
        gephi = controllers()
        for config in configurations():
            if onlyId and config['configId'] != onlyId:
                continue
            recordFile = recordPath / (config['configId'] + '.json')
            if recordFile.exists() and json.loads(recordFile.read_text()).get('complete'):
                print('Gephi done:', config['configId'], flush=True)
                continue
            print('Gephi:', config['configId'], flush=True)
            buildOne(gephi, config)
        writeLayoutTable()
    except Exception:
        import traceback
        traceback.print_exc()
        exitCode = 1
    sys.stdout.flush()
    # Gephi leaves non-daemon AWT threads alive, so the JVM is exited explicitly.
    System.exit(exitCode)

def writeLayoutTable():
    rows = []
    for config in configurations():
        recordFile = recordPath / (config['configId'] + '.json')
        if not recordFile.exists():
            continue
        record = json.loads(recordFile.read_text())
        for view in record['views']:
            rows.append(dict(configId=record['configId'], seed=record['seed'], project=record['project'],
                             workspace=view['workspace'], pdf=view['pdf'], positions=view['positions'],
                             layoutSettings=json.dumps(forceAtlas2Settings) if 'ForceAtlas2' in view['workspace'] else '',
                             style=json.dumps(styleSettings), gephiNodes=view['gephiNodes'], gephiEdges=view['gephiEdges'],
                             seconds=round(view['seconds'], 1)))
    writeCsv(gephiPath / 'gephi_views.csv', rows)

def pdfCheck(pdfFile):
    """PDF is one page, visibly non-blank, and contains one stroke per edge and one fill per node."""
    import pymupdf
    document = pymupdf.open(pdfFile)
    page = document[0]
    content = page.read_contents()
    strokes = content.count(b'\nS\n')
    # Nodes are filled circles drawn with "B" (fill + darker outline) or "f"; minus the white page background.
    fills = content.count(b'\nB\n') + content.count(b'\nf\n') - 1
    pixmap = page.get_pixmap(dpi=40, colorspace=pymupdf.csGRAY)
    samples = pixmap.samples
    inkShare = sum(1 for value in samples if value < 245) / len(samples)
    return dict(pages=len(document), strokes=strokes, fills=fills, inkShare=inkShare)

def verify():
    """Reopen each saved .gephi through Gephi's ProjectController in a NEW JVM and recheck it.

    This is Gephi's own project loader (the code the GUI's File > Open uses), run headless;
    it is not a visual reopening of the GUI window."""
    startGephi()
    from java.io import File
    from java.lang import System
    rows, exitCode = [], 0
    try:
        gephi = controllers()
        for config in configurations():
            record = json.loads((recordPath / (config['configId'] + '.json')).read_text())
            projectFile = projectPath / record['project']
            with zipfile.ZipFile(projectFile) as archive:
                archiveOk = archive.testzip() is None
            nxGraph = nx.read_gml(graphPath / record['gml'], destringizer=int)
            expectedNodes, expectedEdges = graphSignature(nxGraph)
            gephi['project'].openProject(File(str(projectFile)))
            project = gephi['project'].getCurrentProject()
            from org.gephi.project.api import WorkspaceInformation
            for workspace in project.getWorkspaces():
                name = str(workspace.getLookup().lookup(WorkspaceInformation).getName())
                graphModel = gephi['graph'].getGraphModel(workspace)
                nodeIds, edgeSet, nodeCount, edgeCount = gephiSignature(graphModel)
                view = next(view for view in record['views'] if view['workspace'] == name)
                positionError = ''
                if name == 'RGG spatial':
                    # Reopened positions must be the generator coordinates up to one uniform scale.
                    scale = view['uniformScale']
                    gephiPositions = {int(str(node.getId())): (node.x(), node.y()) for node in nodeList(graphModel)}
                    xs = [nxGraph.nodes[nodeId]['pos'][0] for nodeId in nxGraph]
                    ys = [nxGraph.nodes[nodeId]['pos'][1] for nodeId in nxGraph]
                    centerX, centerY = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
                    positionError = max(max(abs(gephiPositions[nodeId][0] / scale - (nxGraph.nodes[nodeId]['pos'][0] - centerX)),
                                            abs(gephiPositions[nodeId][1] / scale - (nxGraph.nodes[nodeId]['pos'][1] - centerY)))
                                        for nodeId in nxGraph)
                rows.append(dict(configId=config['configId'], project=record['project'], workspace=name,
                                 archiveIntegrity=archiveOk, reopenedByGephiLoader=True,
                                 undirected=bool(graphModel.isUndirected()), nodes=nodeCount, edges=edgeCount,
                                 nodeAndEdgeSetsMatchGml=nodeIds == expectedNodes and edgeSet == expectedEdges,
                                 rggMaxPositionError=positionError, pdf=view['pdf']))
            gephi['project'].closeCurrentProject()
            print('Reopened', record['project'], flush=True)
    except Exception:
        import traceback
        traceback.print_exc()
        exitCode = 1
    writeCsv(gephiPath / 'gephi_reopen_check.csv', rows)
    sys.stdout.flush()
    System.exit(exitCode)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=['build', 'verify'])
    parser.add_argument('--only', help='Build one configuration, e.g. BA_n10000_d10')
    arguments = parser.parse_args()
    build(arguments.only) if arguments.command == 'build' else verify()
