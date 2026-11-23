"""Plot completed measurements; these analysis PDFs/PNGs are matplotlib charts, NOT Gephi exports."""
import csv
import json
import os
from collections import defaultdict
from common import outputPath, writeCsv, nValues, targetDegrees, modelColors, wsLineStyles, wsHatches
os.environ.setdefault('MPLCONFIGDIR', str(outputPath / '.matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
figurePath = outputPath / 'plots'
figurePath.mkdir(parents=True, exist_ok=True)
plt.rcParams.update({'axes.spines.top': False, 'axes.spines.right': False, 'axes.grid': True,
                     'grid.alpha': .25, 'lines.linewidth': 1.8, 'legend.fontsize': 8})
# Fixed series order so a model always has the same color, style and legend position.
seriesOrder = ['RGG', 'ER', 'WS p=0.1', 'WS p=0.2', 'WS p=0.3', 'BA']
milestoneFractions = [0.01, 0.05, 0.10, 0.20, 0.30, 0.50]

def readRows(path):
    with path.open(newline='') as stream:
        return list(csv.DictReader(stream))

def seriesName(row):
    return row['model'] + (f" p={float(row['probability']):g}" if row['model'] == 'WS' else '')

def seriesStyle(row):
    """Color by model; WS rewiring probability by line style (lines) or hatch (bars)."""
    probability = float(row['probability']) if row['model'] == 'WS' else None
    return dict(color=modelColors[row['model']], linestyle=wsLineStyles.get(probability, '-'),
                hatch=wsHatches.get(probability, ''))

def saveFigure(figure, name):
    figure.tight_layout()
    for extension in ['png', 'pdf']:
        figure.savefig(figurePath / (name + '.' + extension), dpi=180)
    plt.close(figure)

def degreeProbabilities(configId, maxDegree):
    probabilities = np.zeros(maxDegree + 1)
    for degreeRow in readRows(outputPath / 'structure' / 'degrees' / (configId + '.csv')):
        probabilities[int(degreeRow['degree'])] = float(degreeRow['probability'])
    return probabilities

def structuralPlots():
    rows = readRows(outputPath / 'structure' / 'structural_comparison.csv')
    rows.sort(key=lambda row: seriesOrder.index(seriesName(row)))
    byGroup = defaultdict(list)
    for row in rows:
        byGroup[(int(row['n']), int(row['targetDegree']))].append(row)
    maxDegree = max(int(row['maxDegree']) for row in rows)
    minProbability = 1 / max(nValues)
    # Degree views: rows = target degree, columns = n; identical axes in every panel.
    for view in ['distribution', 'ccdf_loglog']:
        figure, axesGrid = plt.subplots(len(targetDegrees), len(nValues), figsize=(15, 8), sharex=True, sharey=True)
        for rowIndex, targetDegree in enumerate(targetDegrees):
            for columnIndex, nodeCount in enumerate(nValues):
                axes = axesGrid[rowIndex, columnIndex]
                for row in byGroup[(nodeCount, targetDegree)]:
                    probabilities = degreeProbabilities(row['configId'], maxDegree)
                    style = seriesStyle(row)
                    degrees = np.arange(maxDegree + 1)
                    if view == 'distribution':
                        axes.plot(degrees, probabilities, color=style['color'], linestyle=style['linestyle'],
                                  drawstyle='steps-mid', label=seriesName(row))
                    else:
                        ccdf = np.cumsum(probabilities[::-1])[::-1]  # P(K >= k)
                        mask = (degrees > 0) & (ccdf > 0)            # log axes cannot show k=0
                        axes.loglog(degrees[mask], ccdf[mask], color=style['color'], linestyle=style['linestyle'],
                                    label=seriesName(row))
                axes.set_title(f'n={nodeCount:,}, target degree={targetDegree}', fontsize=10)
                if view == 'distribution':
                    # Body of the distribution; BA tails beyond k=60 are shown in the CCDF figure.
                    axes.set(xlim=(0, 60), ylim=(0, 0.5))
                else:
                    axes.set(xlim=(1, maxDegree * 1.2), ylim=(minProbability * .8, 1.05))
                if rowIndex == len(targetDegrees) - 1:
                    axes.set_xlabel('Degree k' + (' (log)' if 'log' in view else ''))
                if columnIndex == 0:
                    axes.set_ylabel('P(K = k)' if view == 'distribution' else 'P(K ≥ k)  (log)')
        axesGrid[0, -1].legend(loc='upper right')
        figure.suptitle('Empirical degree distribution (linear, k ≤ 60; isolates included)' if view == 'distribution'
                        else 'Empirical degree CCDF, log-log (k = 0 omitted). A straight segment alone does not establish a power law.')
        saveFigure(figure, 'degree_' + view)
    # Scaling of structural measures with n: one panel per measure, columns = target degree.
    measures = [('averageClustering', 'Average clustering (log)', 'log'),
                ('estimatedLccMeanPath', 'ESTIMATED LCC mean shortest path\n(64 sampled BFS sources; log)', 'log'),
                ('exactDiameter', 'Exact whole-graph diameter (log)\nhollow marker at bottom = disconnected, N/A', 'log'),
                ('componentCount', 'Connected components\n(isolates included)', None),
                ('lccShare', 'LCC / all nodes', None)]
    figure, axesGrid = plt.subplots(len(measures), len(targetDegrees), figsize=(12, 17), sharex=True, sharey='row')
    for columnIndex, targetDegree in enumerate(targetDegrees):
        for rowIndex, (field, label, scale) in enumerate(measures):
            axes = axesGrid[rowIndex, columnIndex]
            for name in seriesOrder:
                seriesRows = sorted([row for row in rows if seriesName(row) == name and int(row['targetDegree']) == targetDegree],
                                    key=lambda row: int(row['n']))
                style = seriesStyle(seriesRows[0])
                sizes = [int(row['n']) for row in seriesRows]
                values = [float(row[field]) if row[field] != 'N/A' else np.nan for row in seriesRows]
                axes.plot(sizes, values, marker='o', color=style['color'], linestyle=style['linestyle'], label=name)
                if field == 'exactDiameter':
                    # Disconnected graphs have no whole-graph diameter: mark them on the x-axis, never impute.
                    missing = [size for size, row in zip(sizes, seriesRows) if row[field] == 'N/A']
                    # Each model gets its own baseline height so hollow N/A markers never overlap.
                    axes.scatter(missing, [2.2 + .25 * seriesOrder.index(name)] * len(missing), marker='o',
                                 facecolors='none', edgecolors=style['color'], s=60, linewidths=1.6)
            if scale:
                axes.set_yscale(scale)
            if field == 'averageClustering':
                axes.set_ylim(5e-5, 1)
            elif field in ['estimatedLccMeanPath', 'exactDiameter']:
                axes.set_ylim(2, 200)
                axes.set_yticks([2, 5, 10, 20, 50, 100, 200], ['2', '5', '10', '20', '50', '100', '200'])
            elif field == 'componentCount':
                axes.set_ylim(0, 8)
            elif field == 'lccShare':
                axes.set_ylim(.9995, 1.00005)
            axes.set_xscale('log')
            axes.set_xticks(nValues, [f'{value:,}' for value in nValues])
            axes.minorticks_off()
            axes.set_ylabel(label)
            if rowIndex == 0:
                axes.set_title(f'Target degree {targetDegree}')
            if rowIndex == len(measures) - 1:
                axes.set_xlabel('Number of nodes n')
    axesGrid[0, 0].legend(ncol=2)
    figure.suptitle('Structural measures vs. graph size (one realization per configuration)')
    saveFigure(figure, 'structure_scaling')

def resiliencePlots():
    completeRuns = []
    for metadataPath in sorted((outputPath / 'resilience' / 'metadata').glob('*.json')):
        metadata = json.loads(metadataPath.read_text())
        if metadata.get('complete'):
            completeRuns.append((metadata, readRows(outputPath / 'resilience' / 'attacks' / (metadataPath.stem + '.csv'))))
    summaryRows, milestoneRows, halfRows = [], [], []
    fields = [('lccOriginalShare', 'LCC / original nodes', (0, 1.02)), ('componentCount', 'Components (isolates included)', (0, 200))]
    def runsFor(model, targetDegree, strategy):
        return [rows for metadata, rows in completeRuns if metadata['config']['model'] == model
                and metadata['config']['targetDegree'] == targetDegree and metadata['strategy'] == strategy]
    for targetDegree in targetDegrees:
        # Figure 1: all models together; random (mean + min-max band) left, targeted right.
        acrossFigure, acrossAxes = plt.subplots(2, 2, figsize=(12, 8), sharex=True)
        # Figure 2: one row per model; random band vs targeted line on the same axes.
        byModelFigure, byModelAxes = plt.subplots(3, 2, figsize=(12, 11), sharex=True)
        for modelIndex, model in enumerate(['RGG', 'ER', 'BA']):
            color = modelColors[model]
            randomRuns, targetedRuns = runsFor(model, targetDegree, 'random'), runsFor(model, targetDegree, 'targeted')
            assert len(randomRuns) == 5 and len(targetedRuns) == 1
            fractions = np.array([float(row['fractionRemoved']) for row in randomRuns[0]])
            for fieldIndex, (field, label, limits) in enumerate(fields):
                values = np.array([[float(row[field]) for row in rows] for rows in randomRuns])
                meanValues, sdValues = values.mean(axis=0), values.std(axis=0, ddof=1)
                targetedValues = np.array([float(row[field]) for row in targetedRuns[0]])
                for index, fraction in enumerate(fractions):
                    summaryRows.append(dict(model=model, targetDegree=targetDegree, measure=field, removedNodeCount=index,
                                            fractionRemoved=fraction, trials=5, mean=meanValues[index], sampleSd=sdValues[index],
                                            minimum=values[:, index].min(), maximum=values[:, index].max(),
                                            targeted=targetedValues[index]))
                for axes, strategy in [(acrossAxes[fieldIndex, 0], 'random'), (acrossAxes[fieldIndex, 1], 'targeted')]:
                    if strategy == 'random':
                        axes.fill_between(fractions, values.min(axis=0), values.max(axis=0), color=color, alpha=.2, linewidth=0)
                        axes.plot(fractions, meanValues, color=color, label=f'{model} random: 5-trial mean (band = min–max)')
                    else:
                        axes.plot(fractions, targetedValues, color=color, label=f'{model} targeted (adaptive exact betweenness)')
                axes = byModelAxes[modelIndex, fieldIndex]
                axes.fill_between(fractions, values.min(axis=0), values.max(axis=0), color=color, alpha=.2, linewidth=0,
                                  label='random: min–max of 5 trials')
                axes.plot(fractions, meanValues, color=color, label='random: mean of 5 trials')
                axes.plot(fractions, targetedValues, color='#0b0b0b', linestyle='--', linewidth=1.4,
                          label='targeted: adaptive exact betweenness')
                axes.set(ylabel=f'{model}\n{label}', xlim=(0, 1), ylim=limits)
                if modelIndex == 2:
                    axes.set_xlabel('Fraction of original nodes removed')
            # Table-ready milestones: state after removing a given fraction of the 500 nodes.
            for fraction in milestoneFractions:
                index = int(round(fraction * int(randomRuns[0][0]['originalNodeCount'])))
                randomLcc = [float(rows[index]['lccOriginalShare']) for rows in randomRuns]
                randomComponents = [int(rows[index]['componentCount']) for rows in randomRuns]
                milestoneRows.append(dict(model=model, targetDegree=targetDegree, fractionRemoved=fraction, removedNodeCount=index,
                                          randomLccShareMean=np.mean(randomLcc), randomLccShareSd=np.std(randomLcc, ddof=1),
                                          randomComponentsMean=np.mean(randomComponents), randomComponentsSd=np.std(randomComponents, ddof=1),
                                          targetedLccShare=float(targetedRuns[0][index]['lccOriginalShare']),
                                          targetedComponents=int(targetedRuns[0][index]['componentCount'])))
            # Breakdown points. LCC/original < 0.5 is nearly forced by removal itself near f=0.5, so
            # LCC/remaining < 0.5 (giant component no longer holds half the survivors) is also given.
            def firstFraction(rows, denominator):
                return next(float(row['fractionRemoved']) for row in rows if int(row['remainingNodeCount']) > 0 and
                            int(row['lccSize']) / int(row[denominator]) < .5)
            for denominator, measure in [('originalNodeCount', 'LCC/original < 0.5'), ('remainingNodeCount', 'LCC/remaining < 0.5')]:
                randomCrossings = [firstFraction(rows, denominator) for rows in randomRuns]
                halfRows.append(dict(model=model, targetDegree=targetDegree, firstFractionWhere=measure,
                                     randomTrialFractions=' '.join(f'{value:.3f}' for value in randomCrossings),
                                     randomMean=np.mean(randomCrossings), randomSd=np.std(randomCrossings, ddof=1),
                                     targetedFraction=firstFraction(targetedRuns[0], denominator)))
        for fieldIndex, (field, label, limits) in enumerate(fields):
            for columnIndex, title in enumerate(['Random removal', 'Targeted removal (recomputed after every node)']):
                axes = acrossAxes[fieldIndex, columnIndex]
                axes.set(title=title if fieldIndex == 0 else '', ylabel=label, xlim=(0, 1), ylim=limits)
                axes.legend(loc='upper right')
                if fieldIndex == 1:
                    axes.set_xlabel('Fraction of original nodes removed')
        byModelAxes[0, 0].legend(loc='upper right')
        acrossFigure.suptitle(f'Resilience by model | n=500 attack graphs, target degree {targetDegree}; initial state at 0')
        byModelFigure.suptitle(f'Random vs. targeted removal | n=500, target degree {targetDegree}')
        saveFigure(acrossFigure, f'resilience_models_n500_d{targetDegree}')
        saveFigure(byModelFigure, f'resilience_random_vs_targeted_n500_d{targetDegree}')
    writeCsv(outputPath / 'resilience' / 'random_trial_summary.csv', summaryRows)
    writeCsv(outputPath / 'resilience' / 'resilience_milestones.csv', milestoneRows)
    # Fraction removed when LCC/original first falls below 0.5 (a simple breakdown summary).
    writeCsv(outputPath / 'resilience' / 'lcc_half_breakdown.csv', halfRows)

if __name__ == '__main__':
    structuralPlots()
    resiliencePlots()
    print('Analysis plots saved to', figurePath)
