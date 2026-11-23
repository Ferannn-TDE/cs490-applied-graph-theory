# Project 2 input data (not included)

The five institutional course prerequisite networks come from:

> B. Yang, M. Gharebhaygloo, H. R. Rondi, E. Hortis, E. Z. Lostalo, X. Huang and G. Ercal,
> "Comparative analysis of course prerequisite networks for five Midwestern public institutions,"
> *Applied Network Science*, vol. 9, art. 25, 2024. doi:[10.1007/s41109-024-00637-z](https://doi.org/10.1007/s41109-024-00637-z)

Source repository:
<https://github.com/BonanYang/Comparative-Analysis-of-Course-Prerequisite-Networks-for-Five-Midwestern-Public-Institutions>

That repository has no licence, so the graphs are linked here and not redistributed.

## Expected layout

Place one GML file per institution in this folder, using these exact (case-sensitive) names.
If the source files are named differently, rename them or edit `institutionFiles` in
`src/config.py`.

```
project2-cpn-at-scale/
└── data/
    ├── siue.gml   Southern Illinois University Edwardsville
    ├── siuc.gml   Southern Illinois University Carbondale
    ├── uiuc.gml   University of Illinois Urbana-Champaign
    ├── mst.gml    Missouri University of Science and Technology
    └── umkc.gml   University of Missouri–Kansas City
```

To keep the files elsewhere, set `DATA_DIR` to their folder.

## What the code expects in each file

- `graph [ directed 1 ... ]` — every graph is directed.
- Node attributes: `id`, `label` (course code, unique within a graph), `attr1` (department code,
  or `MERGED` for cross-listed nodes) and optionally `flag` (department list on merged nodes).
  Cross-listed or co-requisite courses are one node whose label joins the codes with `/`,
  e.g. `CS374/ECE374`.
- Edge direction: prerequisite → dependent course. Edges have no attributes.

`partB_networkx.py` stops with an error if a graph has duplicate course labels.

## Project 1 graphs (optional)

`src/compareProject1.py` also needs Project 1's SIUE `CS.gml`, `ECE.gml` and `BIOL.gml`. By default
it reads them from `../project1-cpn-exploration/results/gml/`; run that project's
`src/cpn_analysis.py` first, or pass `--project1-dir PATH`.
