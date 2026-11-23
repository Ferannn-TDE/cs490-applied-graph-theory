# Project 1 input data (not included)

The five program CSV files were provided by the course instructor and are not
redistributed here. To run the project, place them in this folder:

```
project1-cpn-exploration/
└── data/
    ├── BIOL.csv
    ├── CS.csv
    ├── ECE.csv
    ├── MATH.csv
    └── ME.csv
```

## Format

Headerless CSV, one row per course:

```
courseX,prereq1,prereq2,...
```

Each row means "courseX has these prerequisites". A course with no prerequisites
is a row with a single cell. Blank cells and blank lines are ignored.

To keep the files elsewhere, set `DATA_DIR` to their folder.
