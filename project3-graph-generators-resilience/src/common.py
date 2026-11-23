"""Shared configuration, reproducible generation, and durable output helpers."""
import csv
import hashlib
import json
import math
import platform
import os
from pathlib import Path
import time
import networkx as nx

# Code lives in src/; results go to the sibling results/ folder unless RESULTS_DIR is set.
basePath = Path(__file__).resolve().parent.parent
outputPath = Path(os.environ.get('RESULTS_DIR', basePath / 'results'))
nValues = [10000, 20000, 50000]
targetDegrees = [10, 20]
wsProbabilities = [0.1, 0.2, 0.3]
nAttack = 500
schemaVersion = 1
# One color per model, shared by every chart and Gephi view (validated for color-vision deficiency).
# The three WS rewiring probabilities share violet and are told apart by line style or hatching.
modelColors = {'RGG': '#2a78d6', 'ER': '#eb6834', 'WS': '#4a3aa7', 'BA': '#1baf7a'}
wsLineStyles = {0.1: '-', 0.2: '--', 0.3: ':'}
wsHatches = {0.1: '', 0.2: '//', 0.3: '..'}

def stableSeed(text):
    # Unlike Python's hash(), this is stable across processes and machines.
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:4], 'big')

def configurations(pilot=False, attack=False):
    sizeValues = [nAttack] if attack else ([10000] if pilot else nValues)
    degreeValues = [10] if pilot else targetDegrees
    for nodeCount in sizeValues:
        for targetDegree in degreeValues:
            for model in ['RGG', 'ER', 'WS', 'BA']:
                if attack and model == 'WS':
                    continue
                probabilities = ([0.1] if pilot else wsProbabilities) if model == 'WS' else [None]
                for probability in probabilities:
                    config = dict(model=model, n=nodeCount, targetDegree=targetDegree)
                    if model == 'RGG':
                        config['radius'] = math.sqrt(targetDegree / (math.pi * nodeCount))
                    elif model == 'ER':
                        config['probability'] = targetDegree / (nodeCount - 1)
                    elif model == 'WS':
                        config.update(k=targetDegree, probability=probability)
                    else:
                        config['m'] = targetDegree // 2
                    config['configId'] = f'{model}_n{nodeCount}_d{targetDegree}' + (f'_p{probability:g}' if model == 'WS' else '')
                    config['seed'] = stableSeed('graph:' + config['configId'])
                    yield config

def generateGraph(config):
    model, nodeCount, seed = config['model'], config['n'], config['seed']
    if model == 'RGG':
        return nx.random_geometric_graph(nodeCount, config['radius'], seed=seed)
    if model == 'ER':
        return nx.gnp_random_graph(nodeCount, config['probability'], seed=seed)
    if model == 'WS':
        return nx.watts_strogatz_graph(nodeCount, config['k'], config['probability'], seed=seed)
    return nx.barabasi_albert_graph(nodeCount, config['m'], seed=seed)

def saveJson(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporaryPath = path.with_suffix(path.suffix + '.tmp')
    temporaryPath.write_text(json.dumps(data, indent=2) + '\n')
    temporaryPath.replace(path)

def writeCsv(path, rows):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporaryPath = path.with_suffix(path.suffix + '.tmp')
    with temporaryPath.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporaryPath.replace(path)

def loadOriginal(config, folder):
    folder.mkdir(parents=True, exist_ok=True)
    graphPath = folder / (config['configId'] + '.gml')
    metadataPath = folder / (config['configId'] + '.json')
    if metadataPath.exists():
        metadata = json.loads(metadataPath.read_text())
        assert metadata['config'] == config and metadata['schemaVersion'] == schemaVersion
        assert metadata['networkxVersion'] == nx.__version__, 'Resume using the recorded NetworkX version.'
        return nx.read_gml(graphPath, destringizer=int), metadata
    startTime = time.perf_counter()
    graph = generateGraph(config)
    generationSeconds = time.perf_counter() - startTime
    graph.graph.update(model=config['model'], seed=config['seed'], targetDegree=config['targetDegree'])
    # Keep NetworkX pos AND Gephi-compatible graphics coordinates for geometric graphs.
    for nodeId, attributes in graph.nodes(data=True):
        if 'pos' in attributes:
            attributes['graphics'] = dict(x=attributes['pos'][0], y=attributes['pos'][1])
    startTime = time.perf_counter()
    temporaryPath = graphPath.with_suffix('.gml.tmp')
    nx.write_gml(graph, temporaryPath)
    temporaryPath.replace(graphPath)
    exportSeconds = time.perf_counter() - startTime
    startTime = time.perf_counter()
    restoredGraph = nx.read_gml(graphPath, destringizer=int)
    assert set(graph) == set(restoredGraph)
    assert {tuple(sorted(edge)) for edge in graph.edges} == {tuple(sorted(edge)) for edge in restoredGraph.edges}
    assert not restoredGraph.is_directed()
    for nodeId, attributes in graph.nodes(data=True):
        if 'pos' in attributes:
            assert all(math.isclose(a, b, abs_tol=1e-15) for a, b in zip(attributes['pos'], restoredGraph.nodes[nodeId]['pos']))
    metadata = dict(config=config, schemaVersion=schemaVersion, networkxVersion=nx.__version__,
                    pythonVersion=platform.python_version(), generationSeconds=generationSeconds,
                    exportSeconds=exportSeconds, roundTripSeconds=time.perf_counter()-startTime,
                    gmlRoundTripValidated=True)
    saveJson(metadataPath, metadata)
    # Use the saved adjacency order immediately as well as after resuming.
    # This keeps floating-point centrality tie behavior consistent across runs.
    return restoredGraph, metadata

def componentState(graph):
    componentSizes = [len(component) for component in nx.connected_components(graph)]
    return max(componentSizes, default=0), len(componentSizes)
