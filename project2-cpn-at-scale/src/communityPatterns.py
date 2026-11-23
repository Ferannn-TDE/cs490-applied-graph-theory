"""
communityPatterns.py - Cross-institution patterns in the Gephi modularity results.

Reads the LCC node tables exported by gephiPipeline.py (memberships for every
resolution) and answers: for comparable department families (calculus MATH,
PHYS, CHEM, BIOL, CS, ECE, ...), which community holds most of each family's
courses, how fragmented each family is, and which family pairs land in the
same community at every institution vs. only at some.

Run from the project2-cpn-at-scale folder:
    .venv/bin/python src/communityPatterns.py
"""
import csv
from collections import Counter, defaultdict
from itertools import combinations

import config
from cpnCommon import courseDepartments

# Department families: comparable codes across the five institutions.
departmentFamilies = {
    "MATH": ["MATH"],
    "STAT": ["STAT"],
    "PHYS": ["PHYS", "PHYSICS"],
    "CHEM": ["CHEM"],
    "BIOL": ["BIOL", "BIOSCI", "BIOLOGY", "IB", "MCB"],
    "CS": ["CS", "COMPSCI"],
    "ECE": ["ECE", "ELECENG", "COMPENG", "ECENGR"],
    "ME": ["ME", "MECHENG", "MECENGR"],
    "CIVIL": ["CE", "CIVENG", "CIVENGR", "CEE"],
    "ECON": ["ECON"],
    "PSYC": ["PSYC", "PSYCH"],
    "SPAN": ["SPAN"],
}
familyOfCode = {code: fam for fam, codes in departmentFamilies.items() for code in codes}
minFamilyCourses = 5     # ignore families with fewer LCC courses at an institution


def main():
    fragmentRows, pairRows = [], []
    pairTogether = defaultdict(lambda: defaultdict(list))   # resolution -> pair -> [inst...]
    pairPresent = defaultdict(lambda: defaultdict(list))
    for inst in config.institutionFiles:
        path = config.gephiTablesDir / "institutions" / f"{inst}_LCC_gephi_nodes_modularity.csv"
        rows = list(csv.DictReader(open(path, newline="")))
        for resolution in config.modularityResolutions:
            col = f"modClass_res{str(resolution).replace('.', '_')}"
            familyComms = defaultdict(Counter)
            for row in rows:
                for code in courseDepartments(row["Label"]):
                    if code in familyOfCode:
                        familyComms[familyOfCode[code]][row[col]] += 1
            plurality = {}
            for fam, comms in familyComms.items():
                total = sum(comms.values())
                if total < minFamilyCourses:
                    continue
                topComm, topCount = comms.most_common(1)[0]
                plurality[fam] = topComm
                fragmentRows.append({"institution": inst, "resolution": resolution, "family": fam,
                                     "lccCourses": total, "communitiesUsed": len(comms),
                                     "pluralityCommunity": topComm,
                                     "shareInPluralityCommunity": round(topCount / total, 3)})
            for a, b in combinations(sorted(plurality), 2):
                pairPresent[resolution][(a, b)].append(inst)
                if plurality[a] == plurality[b]:
                    pairTogether[resolution][(a, b)].append(inst)
    for resolution, pairs in pairPresent.items():
        for (a, b), insts in sorted(pairs.items()):
            together = pairTogether[resolution][(a, b)]
            if not together:
                continue
            pairRows.append({"resolution": resolution, "familyA": a, "familyB": b,
                             "institutionsWithBoth": len(insts), "institutionsSameCommunity": len(together),
                             "sameCommunityAt": "+".join(together),
                             "pattern": "always together" if len(together) == len(insts) else "sometimes"})
    outDir = config.gephiTablesDir
    for name, data in [("community_family_fragmentation.csv", fragmentRows),
                       ("community_family_pairs.csv", pairRows)]:
        with open(outDir / name, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(data[0].keys()))
            writer.writeheader()
            writer.writerows(data)
    for row in pairRows:
        if row["pattern"] == "always together" or row["institutionsSameCommunity"] >= 3:
            print(row)


if __name__ == "__main__":
    main()
