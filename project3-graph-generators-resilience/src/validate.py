"""Check algorithms and saved artifacts; optional expensive targeted audit."""
import argparse
import csv
import json
import math
import random
import tempfile
from pathlib import Path
from unittest.mock import patch
import networkx as nx
from common import configurations, generateGraph, componentState, outputPath, loadOriginal, writeCsv
from experiments import selectTarget, runAttack, attackRow

def algorithmChecks():
    configs = list(configurations())
    assert len(configs) == len({config['configId'] for config in configs}) == 36
    assert len(list(configurations(pilot=True))) == 4
    assert len(list(configurations(attack=True))) == 6
    assert {config['m'] for config in configs if config['model'] == 'BA'} == {5, 10}
    for config in configurations(pilot=True):
        smallConfig = dict(config, n=40)
        firstGraph, secondGraph = generateGraph(smallConfig), generateGraph(smallConfig)
        assert set(firstGraph.edges) == set(secondGraph.edges) and len(firstGraph) == 40
        assert sum(dict(firstGraph.degree()).values()) == 2 * firstGraph.number_of_edges()
    assert componentState(nx.empty_graph(3)) == (1, 3)
    assert componentState(nx.Graph()) == (0, 0)
    with tempfile.TemporaryDirectory() as temporaryDirectory:
        folder = Path(temporaryDirectory)
        graph = nx.path_graph(5)
        graph.add_node(5)
        exactFunction = nx.betweenness_centrality
        observedGraphs = []
        def checkedBetweenness(currentGraph, **options):
            assert options['k'] is None
            observedGraphs.append(set(currentGraph))
            return exactFunction(currentGraph, **options)
        with patch('experiments.nx.betweenness_centrality', side_effect=checkedBetweenness):
            rows = runAttack(graph, folder / 'targeted.csv', 'targeted', None)
        assert [len(nodes) for nodes in observedGraphs] == list(range(6, 0, -1))
        assert rows[1]['removedNode'] == 2 and rows[2]['removedNode'] == 0
        assert rows[0]['componentCount'] == 2
        assert rows[-1]['lccSize'] == rows[-1]['componentCount'] == 0
        assert len(graph) == 6
        replayGraph = graph.copy()
        for row in rows[1:]:
            selectedNode, score = selectTarget(replayGraph)
            assert row['removedNode'] == selectedNode and row['selectedBetweenness'] == score
            replayGraph.remove_node(selectedNode)
        randomRows = runAttack(graph, folder / 'random.csv', 'random', 123)
        (folder / 'random.csv').unlink()
        repeatedRows = runAttack(graph, folder / 'random.csv', 'random', 123)
        assert [row['removedNode'] for row in randomRows] == [row['removedNode'] for row in repeatedRows]
        writeCsv(folder / 'random.csv', randomRows[:3])
        resumedRows = runAttack(graph, folder / 'random.csv', 'random', 123)
        assert [str(row['removedNode']) for row in randomRows] == [str(row['removedNode']) for row in resumedRows]
        config = dict(next(configurations(attack=True)), n=30, configId='RGG_test_n30')
        firstGraph, firstMetadata = loadOriginal(config, folder / 'graphs')
        loadedGraph, loadedMetadata = loadOriginal(config, folder / 'graphs')
        assert set(firstGraph.edges) == set(loadedGraph.edges) and firstMetadata == loadedMetadata
    print('Algorithm checks passed: 36 configurations, seeds, degree identity, GML coordinates, exact adaptive attacks, ties, empty state, resume.')

def savedChecks(auditTargeted=False, requireComplete=False):
    structuralCount, attackCount = 0, 0
    structuralIds = set()
    completeAttackCount = 0
    for path in (outputPath / 'structure' / 'checkpoints').glob('*.json'):
        result = json.loads(path.read_text())
        if not result.get('complete'):
            continue
        graph = nx.read_gml(outputPath / 'structure' / 'graphs' / (result['configId'] + '.gml'), destringizer=int)
        assert len(graph) == result['n'] == result['actualNodes']
        assert graph.number_of_edges() == result['actualEdges']
        assert not graph.is_directed() and not graph.is_multigraph()
        degrees = dict(graph.degree())
        assert min(degrees.values()) == result['minDegree']
        assert max(degrees.values()) == result['maxDegree']
        assert math.isclose(result['actualAverageDegree'], 2*graph.number_of_edges()/len(graph))
        assert componentState(graph) == (result['lccSize'], result['componentCount'])
        assert nx.is_connected(graph) == result['connected']
        assert result['connected'] or result['exactDiameter'] == 'N/A'
        with (outputPath / 'structure' / 'degrees' / (result['configId'] + '.csv')).open() as stream:
            rows = list(csv.DictReader(stream))
        assert sum(int(row['count']) for row in rows) == len(graph)
        assert sum(int(row['degree'])*int(row['count']) for row in rows) == 2*graph.number_of_edges()
        if result['model'] == 'RGG':
            assert all(len(attributes['pos']) == 2 for nodeId, attributes in graph.nodes(data=True))
        assert result['pathSampleSize'] == len(result['pathSources'])
        structuralCount += 1
        structuralIds.add(result['configId'])
    for metadataPath in (outputPath / 'resilience' / 'metadata').glob('*.json'):
        metadata = json.loads(metadataPath.read_text())
        graph = nx.read_gml(outputPath / 'resilience' / 'graphs' / metadata['originalGraph'], destringizer=int)
        originalCount = len(graph)
        randomGenerator = random.Random(metadata['attackSeed'])
        with (outputPath / 'resilience' / 'attacks' / (metadataPath.stem + '.csv')).open() as stream:
            rows = list(csv.DictReader(stream))
        if metadata['complete']:
            assert len(rows) == originalCount + 1
            completeAttackCount += 1
        for index, row in enumerate(rows):
            if index:
                removedNode = int(row['removedNode'])
                if metadata['strategy'] == 'random':
                    assert removedNode == randomGenerator.choice(sorted(graph))
                if auditTargeted and metadata['strategy'] == 'targeted':
                    expectedNode, expectedScore = selectTarget(graph)
                    assert removedNode == expectedNode
                    assert math.isclose(float(row['selectedBetweenness']), expectedScore, abs_tol=1e-14)
                graph.remove_node(removedNode)
            expectedRow = attackRow(graph, originalCount, index)
            for field in ['originalNodeCount', 'removedNodeCount', 'remainingNodeCount', 'lccSize', 'componentCount']:
                assert int(row[field]) == expectedRow[field]
            for field in ['fractionRemoved', 'lccOriginalShare']:
                assert math.isclose(float(row[field]), expectedRow[field], abs_tol=1e-14)
        attackCount += 1
    if requireComplete:
        assert structuralIds == {config['configId'] for config in configurations()}
        assert completeAttackCount == attackCount == 36
        assert len(list((outputPath / 'resilience' / 'graphs').glob('*.gml'))) == 6
    print(f'Saved artifacts validated: {structuralCount} structural graphs, {attackCount} attack runs.')

def deepChecks(diameterCheckSize=10000):
    """Independent recomputation of saved results (minutes, not hours)."""
    import statistics
    import numpy as np
    from common import generateGraph
    for config in configurations():
        checkpoint = json.loads((outputPath / 'structure' / 'checkpoints' / (config['configId'] + '.json')).read_text())
        gmlPath = outputPath / 'structure' / 'graphs' / (config['configId'] + '.gml')
        gmlText = gmlPath.read_text()
        graph = nx.read_gml(gmlPath, destringizer=int)  # raises on duplicate edges in a simple graph
        # Raw file: undirected, simple, and one "edge [" block per saved edge.
        assert 'directed 1' not in gmlText and 'multigraph 1' not in gmlText
        assert gmlText.count('edge [') == graph.number_of_edges()
        assert nx.number_of_selfloops(graph) == 0
        # Reproducibility: the recorded seed regenerates exactly the saved graph.
        regenerated = generateGraph(config)
        assert set(regenerated) == set(graph)
        assert {tuple(sorted(edge)) for edge in regenerated.edges} == {tuple(sorted(edge)) for edge in graph.edges}
        if config['model'] == 'RGG':
            assert all(math.isclose(regenerated.nodes[nodeId]['pos'][axis], graph.nodes[nodeId]['pos'][axis], abs_tol=1e-15)
                       for nodeId in graph for axis in (0, 1))
        assert math.isclose(nx.average_clustering(graph), checkpoint['averageClustering'], rel_tol=1e-12)
        if checkpoint['connected'] and config['n'] == diameterCheckSize:
            # Independent recheck with plain all-eccentricity diameter (no bounds); n BFS runs, so n=10000 only.
            assert nx.diameter(graph) == checkpoint['exactDiameter']
        assert checkpoint['connected'] or (checkpoint['exactDiameter'] == 'N/A' and 'N/A' in checkpoint['diameterMethod'])
        # The ESTIMATED path value is reproduced from its recorded BFS sources and seed.
        lccNodes = max(nx.connected_components(graph), key=lambda nodes: (len(nodes), -min(nodes)))
        lccGraph = graph.subgraph(lccNodes)
        expectedSources = random.Random(checkpoint['pathSampleSeed']).sample(sorted(lccNodes), checkpoint['pathSampleSize'])
        assert expectedSources == checkpoint['pathSources']
        estimate = statistics.mean(sum(nx.single_source_shortest_path_length(lccGraph, source).values()) / (len(lccGraph) - 1)
                                   for source in expectedSources)
        assert math.isclose(estimate, checkpoint['estimatedLccMeanPath'], rel_tol=1e-12)
        print('  deep structural check passed:', config['configId'], flush=True)
    # Attack graphs: regenerate from seeds; every run starts from the same original state.
    runsByGraph = {}
    for metadataPath in sorted((outputPath / 'resilience' / 'metadata').glob('*.json')):
        metadata = json.loads(metadataPath.read_text())
        with (outputPath / 'resilience' / 'attacks' / (metadataPath.stem + '.csv')).open() as stream:
            rows = list(csv.DictReader(stream))
        runsByGraph.setdefault(metadata['config']['configId'], []).append((metadata, rows))
        removedNodes = [int(row['removedNode']) for row in rows[1:]]
        assert len(removedNodes) == len(set(removedNodes)) == int(rows[0]['originalNodeCount'])
        for previous, current in zip(rows, rows[1:]):
            assert int(current['remainingNodeCount']) == int(previous['remainingNodeCount']) - 1  # exactly one node
            assert int(current['lccSize']) <= int(previous['lccSize'])                             # LCC never grows
        assert int(rows[-1]['lccSize']) == int(rows[-1]['componentCount']) == int(rows[-1]['remainingNodeCount']) == 0
    for config in configurations(attack=True):
        graph = nx.read_gml(outputPath / 'resilience' / 'graphs' / (config['configId'] + '.gml'), destringizer=int)
        regenerated = generateGraph(config)
        assert {tuple(sorted(edge)) for edge in regenerated.edges} == {tuple(sorted(edge)) for edge in graph.edges}
        runs = runsByGraph[config['configId']]
        assert len(runs) == 6 and sorted(metadata['strategy'] for metadata, rows in runs) == ['random'] * 5 + ['targeted']
        initialStates = {tuple(rows[0][field] for field in ['originalNodeCount', 'lccSize', 'componentCount']) for metadata, rows in runs}
        assert initialStates == {(str(len(graph)),) + tuple(str(value) for value in componentState(graph))}
        assert len({metadata['attackSeed'] for metadata, rows in runs if metadata['strategy'] == 'random'}) == 5
    # Chart data = tables: recompute the random-trial summary from the attack CSVs.
    with (outputPath / 'resilience' / 'random_trial_summary.csv').open() as stream:
        summary = list(csv.DictReader(stream))
    for row in summary:
        runs = runsByGraph[f"{row['model']}_n500_d{row['targetDegree']}"]
        values = [float(rows[int(row['removedNodeCount'])][row['measure']]) for metadata, rows in runs if metadata['strategy'] == 'random']
        targeted = [float(rows[int(row['removedNodeCount'])][row['measure']]) for metadata, rows in runs if metadata['strategy'] == 'targeted'][0]
        assert math.isclose(float(row['mean']), np.mean(values), abs_tol=1e-12)
        assert math.isclose(float(row['minimum']), min(values)) and math.isclose(float(row['maximum']), max(values))
        assert math.isclose(float(row['targeted']), targeted)
    print(f'Deep checks passed: 36 regenerated/remeasured graphs, 6 attack graphs, 36 attack runs, {len(summary)} summary rows.')

def gephiChecks():
    """Gephi records, PDFs (non-blank; one stroke per edge, one fill per node) and the reopen table."""
    from gephiPipeline import recordPath, pdfPath, gephiPath, pdfCheck
    with (gephiPath / 'gephi_reopen_check.csv').open() as stream:
        reopenRows = list(csv.DictReader(stream))
    pdfRows = []
    for config in configurations():
        record = json.loads((recordPath / (config['configId'] + '.json')).read_text())
        checkpoint = json.loads((outputPath / 'structure' / 'checkpoints' / (config['configId'] + '.json')).read_text())
        assert record['complete'] and str(config['seed']) in record['project']
        expectedViews = 2 if config['model'] in ['RGG', 'WS'] else 1
        assert len(record['views']) == expectedViews
        workspaceRows = [row for row in reopenRows if row['configId'] == config['configId']]
        assert len(workspaceRows) == expectedViews
        for row in workspaceRows:
            assert row['archiveIntegrity'] == row['reopenedByGephiLoader'] == row['undirected'] == row['nodeAndEdgeSetsMatchGml'] == 'True'
            assert (int(row['nodes']), int(row['edges'])) == (checkpoint['actualNodes'], checkpoint['actualEdges'])
            if row['workspace'] == 'RGG spatial':
                assert float(row['rggMaxPositionError']) < 1e-6  # float32 storage of unit-square coordinates
        for view in record['views']:
            result = pdfCheck(pdfPath / view['pdf'])
            assert result['pages'] == 1 and result['inkShare'] > .02
            assert result['strokes'] == checkpoint['actualEdges'] and result['fills'] == checkpoint['actualNodes'], (view['pdf'], result)
            pdfRows.append(dict(pdf=view['pdf'], expectedEdges=checkpoint['actualEdges'], pdfEdgeStrokes=result['strokes'],
                                expectedNodes=checkpoint['actualNodes'], pdfNodeFills=result['fills'], inkShare=round(result['inkShare'], 4)))
    writeCsv(gephiPath / 'gephi_pdf_check.csv', pdfRows)
    print(f'Gephi checks passed: 36 projects reopened, {len(reopenRows)} workspaces, {len(pdfRows)} PDFs match their graphs.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit-targeted', action='store_true', help='Expensive: recompute every saved targeted selection.')
    parser.add_argument('--require-complete', action='store_true', help='Require all 36 structural graphs and all 36 complete attack runs.')
    parser.add_argument('--deep', action='store_true', help='Regenerate graphs from seeds and recompute measures (minutes).')
    parser.add_argument('--gephi', action='store_true', help='Check Gephi records, PDFs and the reopen table.')
    arguments = parser.parse_args()
    algorithmChecks()
    savedChecks(arguments.audit_targeted, arguments.require_complete)
    if arguments.deep:
        deepChecks()
    if arguments.gephi:
        gephiChecks()
