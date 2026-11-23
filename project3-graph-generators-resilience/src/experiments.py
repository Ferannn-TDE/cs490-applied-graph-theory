"""Run structural measurements or complete sequential resilience experiments."""
import argparse
import csv
import fcntl
import json
import random
import statistics
import time
import networkx as nx
from common import (configurations, loadOriginal, outputPath, saveJson, writeCsv,
                    stableSeed, componentState, schemaVersion)

pathSampleSize = 64

def structuralRun(pilot=False):
    folder = outputPath / 'structure'
    for config in configurations(pilot=pilot):
        resultPath = folder / 'checkpoints' / (config['configId'] + '.json')
        print('Structure:', config['configId'], flush=True)
        graph, metadata = loadOriginal(config, folder / 'graphs')
        result = json.loads(resultPath.read_text()) if resultPath.exists() else dict(
            **config, schemaVersion=schemaVersion, **{key: metadata[key] for key in
            ['networkxVersion', 'pythonVersion', 'generationSeconds', 'exportSeconds', 'roundTripSeconds', 'gmlRoundTripValidated']})
        assert all(result[key] == value for key, value in config.items())
        def recordMeasure(name, calculation):
            if name in result:
                return
            startTime = time.perf_counter()
            result.update(calculation())
            result[name + 'Seconds'] = time.perf_counter() - startTime
            saveJson(resultPath, result)
            print(f"  {name}: {result[name]} ({result[name + 'Seconds']:.2f}s)", flush=True)
        def degreeMeasures():
            degrees = [degree for nodeId, degree in graph.degree()]
            averageDegree = statistics.mean(degrees)
            assert sum(degrees) == 2 * graph.number_of_edges()
            assert averageDegree == 2 * graph.number_of_edges() / len(graph)
            frequencies = {degree: degrees.count(degree) for degree in sorted(set(degrees))}
            writeCsv(folder / 'degrees' / (config['configId'] + '.csv'),
                     [dict(degree=degree, count=count, probability=count/len(graph)) for degree, count in frequencies.items()])
            return dict(actualNodes=len(graph), actualEdges=graph.number_of_edges(),
                        minDegree=min(degrees), maxDegree=max(degrees), actualAverageDegree=averageDegree)
        recordMeasure('actualNodes', degreeMeasures)
        def connectivityMeasures():
            lccSize, componentCount = componentState(graph)
            return dict(connected=nx.is_connected(graph), componentCount=componentCount,
                        lccSize=lccSize, lccShare=lccSize/len(graph))
        recordMeasure('connected', connectivityMeasures)
        recordMeasure('averageClustering', lambda: dict(averageClustering=nx.average_clustering(graph)))
        recordMeasure('exactDiameter', lambda: dict(exactDiameter=nx.diameter(graph, usebounds=True) if result['connected'] else 'N/A',
                                                  diameterMethod='exact usebounds' if result['connected'] else 'N/A disconnected'))
        def estimatedPaths():
            lccNodes = max(nx.connected_components(graph), key=lambda nodes: (len(nodes), -min(nodes)))
            lccGraph = graph.subgraph(lccNodes)
            sampleSeed = stableSeed('paths:' + config['configId'])
            sourceNodes = random.Random(sampleSeed).sample(sorted(lccNodes), min(pathSampleSize, len(lccNodes)))
            sourceMeans = [sum(nx.single_source_shortest_path_length(lccGraph, source).values()) / (len(lccGraph)-1)
                           if len(lccGraph)>1 else 0 for source in sourceNodes]
            return dict(estimatedLccMeanPath=statistics.mean(sourceMeans), pathSampleSize=len(sourceNodes),
                        pathSampleSeed=sampleSeed, pathSources=sourceNodes, pathMeasure='estimated LCC mean shortest path')
        recordMeasure('estimatedLccMeanPath', estimatedPaths)
        result['complete'] = True
        saveJson(resultPath, result)
        exportStructure(folder)

def exportStructure(folder):
    rows = []
    for path in sorted((folder / 'checkpoints').glob('*.json')):
        result = json.loads(path.read_text())
        if result.get('complete'):
            rows.append({key: result.get(key, '') for key in structureFields})
    writeCsv(folder / 'structural_comparison.csv', rows)

structureFields = ['configId', 'model', 'n', 'targetDegree', 'radius', 'probability', 'k', 'm', 'seed',
                   'actualNodes', 'actualEdges', 'connected', 'componentCount', 'lccSize', 'lccShare',
                   'minDegree', 'maxDegree', 'actualAverageDegree', 'averageClustering', 'exactDiameter',
                   'diameterMethod', 'estimatedLccMeanPath', 'pathMeasure', 'pathSampleSize', 'pathSampleSeed',
                   'generationSeconds', 'exportSeconds', 'roundTripSeconds', 'actualNodesSeconds', 'connectedSeconds',
                   'averageClusteringSeconds', 'exactDiameterSeconds', 'estimatedLccMeanPathSeconds', 'networkxVersion', 'pythonVersion']

def selectTarget(graph):
    # k=None means all sources: exact betweenness on the CURRENT remaining graph.
    scores = nx.betweenness_centrality(graph, k=None, normalized=True, weight=None, endpoints=False)
    selectedNode = min(scores, key=lambda nodeId: (-scores[nodeId], nodeId))
    return selectedNode, scores[selectedNode]

def attackRow(graph, originalCount, removedCount, removedNode='', score='', selectionSeconds=0):
    startTime = time.perf_counter()
    lccSize, componentCount = componentState(graph)
    return dict(originalNodeCount=originalCount, removedNodeCount=removedCount,
                fractionRemoved=removedCount/originalCount, remainingNodeCount=len(graph),
                lccSize=lccSize, lccOriginalShare=lccSize/originalCount, componentCount=componentCount,
                removedNode=removedNode, selectedBetweenness=score, selectionSeconds=selectionSeconds,
                stateSeconds=time.perf_counter()-startTime)

def runAttack(originalGraph, resultPath, strategy, attackSeed):
    graph = originalGraph.copy()
    originalCount = len(graph)
    randomGenerator = random.Random(attackSeed)
    rows = []
    if resultPath.exists():
        with resultPath.open(newline='') as stream:
            rows = list(csv.DictReader(stream))
        assert len(rows) <= originalCount + 1
        assert int(rows[0]['removedNodeCount']) == 0
        for removedCount, row in enumerate(rows[1:], 1):
            assert int(row['removedNodeCount']) == removedCount
            removedNode = int(row['removedNode'])
            if strategy == 'random':
                assert randomGenerator.choice(sorted(graph)) == removedNode
            graph.remove_node(removedNode)
        assert int(rows[-1]['remainingNodeCount']) == len(graph)
    else:
        rows = [attackRow(graph, originalCount, 0)]
        writeCsv(resultPath, rows)
    while graph:
        startTime = time.perf_counter()
        if strategy == 'targeted':
            removedNode, score = selectTarget(graph)
        else:
            removedNode, score = randomGenerator.choice(sorted(graph)), ''
        selectionSeconds = time.perf_counter() - startTime
        graph.remove_node(removedNode)
        removedCount = originalCount-len(graph)
        rows.append(attackRow(graph, originalCount, removedCount, removedNode, score, selectionSeconds))
        # Atomic per-removal checkpoint. Replay restores the remaining graph and RNG.
        writeCsv(resultPath, rows)
        if removedCount % 50 == 0:
            print(f'  {strategy}: {removedCount}/{originalCount} removed', flush=True)
    return rows

def resilienceRun():
    folder = outputPath / 'resilience'
    for config in configurations(attack=True):
        print('Resilience:', config['configId'], flush=True)
        originalGraph, metadata = loadOriginal(config, folder / 'graphs')
        for strategy, trials in [('random', range(1, 6)), ('targeted', [0])]:
            for trial in trials:
                attackSeed = stableSeed(f"attack:{config['configId']}:{trial}") if strategy == 'random' else None
                runId = f"{config['configId']}_{strategy}" + (f'_trial{trial}' if trial else '')
                metadataPath = folder / 'metadata' / (runId + '.json')
                attackMetadata = dict(config=config, strategy=strategy, trial=trial, attackSeed=attackSeed,
                                     schemaVersion=schemaVersion, networkxVersion=nx.__version__,
                                     originalGraph=config['configId'] + '.gml',
                                     tieRule='smallest integer node ID among exactly equal maximum scores',
                                     betweenness='exact; k=None; recomputed after every removal', complete=False)
                if metadataPath.exists():
                    previousMetadata = json.loads(metadataPath.read_text())
                    assert all(previousMetadata[key] == value for key, value in attackMetadata.items() if key != 'complete')
                saveJson(metadataPath, attackMetadata)
                rows = runAttack(originalGraph, folder / 'attacks' / (runId + '.csv'), strategy, attackSeed)
                attackMetadata.update(complete=True, records=len(rows),
                                     selectionSeconds=sum(float(row['selectionSeconds']) for row in rows),
                                     stateSeconds=sum(float(row['stateSeconds']) for row in rows))
                saveJson(metadataPath, attackMetadata)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['pilot', 'structure', 'resilience'])
    arguments = parser.parse_args()
    # Pilot and full structure share outputs; prevent concurrent writers.
    outputPath.mkdir(parents=True, exist_ok=True)
    lockName = 'resilience' if arguments.command == 'resilience' else 'structure'
    with (outputPath / (lockName + '.lock')).open('w') as lockStream:
        try:
            fcntl.flock(lockStream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.exit(1, 'This experiment is already running; wait for it to finish.\n')
        if arguments.command == 'resilience':
            resilienceRun()
        else:
            structuralRun(pilot=arguments.command == 'pilot')
