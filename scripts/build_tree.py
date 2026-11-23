#!/usr/bin/env python3
"""Aggregate the module graph into a prefix tree (depth <= MAXD) for the HTML viewer.

Mechanical only: node names are real Lean module path components. Nothing generated.

Per node:
  n    modules rolled up under it
  loc  lines of source
  th   theorems+lemmas, df defs+abbrevs, st structures+classes+inductives, ins instances
  dist minimum import distance from Main (0 = Main) over its modules  ("proof depth")
  out  top outgoing dependencies  [[node_id, module_import_edge_count], ...]  (same-depth nodes)
  inn  top incoming dependencies
  top  biggest modules (by theorem count) inside, for leaves only: [[name, loc, thms], ...]

Output: out/tree.json
"""
import collections
import gzip
import json
import os

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out")
MAXD = 4
TOPK = 8
TOPMODS = 6

mods = {}
for line in gzip.open(os.path.join(OUT, "modules.jsonl.gz"), "rt"):
    r = json.loads(line)
    mods[r["m"]] = r

# BFS distance from Main along imports (internal modules only).
dist = {"Main": 0}
queue = collections.deque(["Main"])
while queue:
    m = queue.popleft()
    for i in mods[m]["imp"]:
        if i in mods and i not in dist:
            dist[i] = dist[m] + 1
            queue.append(i)


def prefix(m: str, d: int) -> str:
    return ".".join(m.split(".")[:d])


# node registry
ids = {}
nodes = []


def node_id(name: str) -> int:
    if name in ids:
        return ids[name]
    nid = len(nodes)
    ids[name] = nid
    nodes.append(
        {
            "name": name,
            "depth": name.count(".") + 1,
            "p": -1,
            "c": [],
            "n": 0,
            "loc": 0,
            "th": 0,
            "df": 0,
            "st": 0,
            "ins": 0,
            "dist": None,
            "reach": 0,
            "_mods": [],
        }
    )
    return nid


KIND = {
    "theorem": "th", "lemma": "th",
    "def": "df", "abbrev": "df",
    "structure": "st", "class": "st", "inductive": "st",
    "instance": "ins",
}

# 1. roll modules up into every prefix node of depth 1..MAXD
for m, r in mods.items():
    parts = m.split(".")
    cnt = collections.Counter(KIND.get(k) for k, _, _ in r["d"])
    thms = cnt.get("th", 0)
    for d in range(1, min(len(parts), MAXD) + 1):
        nm = ".".join(parts[:d])
        nid = node_id(nm)
        nd = nodes[nid]
        nd["n"] += 1
        nd["loc"] += r["loc"]
        for key in ("th", "df", "st", "ins"):
            nd[key] += cnt.get(key, 0)
        if m in dist:
            nd["reach"] += 1
            if nd["dist"] is None or dist[m] < nd["dist"]:
                nd["dist"] = dist[m]
        if d == min(len(parts), MAXD):
            nd["_mods"].append((m, r["loc"], thms))

# 2. parent/children links
for nid, nd in enumerate(nodes):
    if nd["depth"] > 1:
        pid = ids[".".join(nd["name"].split(".")[:-1])]
        nd["p"] = pid
        nodes[pid]["c"].append(nid)

# 3. aggregated dependency edges per depth
out_e = collections.defaultdict(collections.Counter)
in_e = collections.defaultdict(collections.Counter)
def add_edge(a: str, b: str):
    if a != b:
        ia, ib = ids[a], ids[b]
        out_e[ia][ib] += 1
        in_e[ib][ia] += 1


for m, r in mods.items():
    L = m.count(".") + 1
    for i in r["imp"]:
        if i not in mods:
            continue
        # A source is counted at depth d only if it actually has d path parts, so a shallow
        # module is never counted at several depths under one node.
        shallow_leaf = L < MAXD and not nodes[ids[m]]["c"]
        for d in range(1, min(L, MAXD) + 1):
            if shallow_leaf and d == L:
                continue  # replaced by the detailed edge below
            add_edge(prefix(m, d), prefix(i, d))
        # Shallow leaf module (e.g. Main, Statements): list its direct imports at full detail.
        if shallow_leaf:
            add_edge(m, prefix(i, MAXD))

for nid, nd in enumerate(nodes):
    nd["out"] = [[k, v] for k, v in out_e[nid].most_common(TOPK)]
    nd["inn"] = [[k, v] for k, v in in_e[nid].most_common(TOPK)]
    nd["nout"] = len(out_e[nid])
    nd["nin"] = len(in_e[nid])
    mm = sorted(nd["_mods"], key=lambda x: (-x[2], -x[1]))[:TOPMODS]
    nd["top"] = [[a, b, c] for a, b, c in mm] if nd["depth"] == MAXD or not nd["c"] else []
    del nd["_mods"]
    # children sorted by loc desc
    nd["c"].sort(key=lambda c: -nodes[c]["loc"])

roots = [i for i, nd in enumerate(nodes) if nd["p"] == -1]
roots.sort(key=lambda i: -nodes[i]["loc"])

meta = {
    "modules": len(mods),
    "reachable": len(dist),
    "loc": sum(r["loc"] for r in mods.values()),
    "decls": sum(len(r["d"]) for r in mods.values()),
    "edges": sum(1 for r in mods.values() for i in r["imp"] if i in mods),
    "maxdist": max(dist.values()),
    "maxd": MAXD,
}
with open(os.path.join(OUT, "tree.json"), "w") as f:
    json.dump({"meta": meta, "roots": roots, "nodes": nodes}, f, ensure_ascii=False, separators=(",", ":"))
print(meta)
print("nodes", len(nodes), "size", os.path.getsize(os.path.join(OUT, "tree.json")) // 1024, "KB")
