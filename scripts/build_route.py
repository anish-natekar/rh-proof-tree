#!/usr/bin/env python3
"""Build the declaration-level 'proof route' and 'structure' data for the viewer.

Roots: the 5 theorems in Main.lean. Edges: name mentions (see extract_decls.py; approximate).
BFS from the roots gives each declaration a depth and a first-found parent. We embed only
declarations with BFS depth <= DMAX (the glance view). For each embedded node we also store a
folder histogram of everything first-found underneath it (its BFS subtree), which is the
abstraction: "this lemma pulls in 40k declarations, mostly from <folder>".

Output: out/route.json
"""
import collections
import gzip
import json
import os
import subprocess

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
DMAX = 7
FOLDER_DEPTH = 3
TOPF = 5

D = json.load(gzip.open(os.path.join(OUT, "decls.json.gz"), "rt"))
E = np.load(os.path.join(OUT, "edges.npz"))
names, kinds, mod, line, nl = D["names"], D["kinds"], D["mod"], D["line"], D["nl"]
mods = D["mods"]
n = len(names)
src, dst = E["src"], E["dst"]

order = np.argsort(src, kind="stable")
s_sorted, d_sorted = src[order], dst[order]
ptr = np.searchsorted(s_sorted, np.arange(n + 1))

roots = [i for i in range(n) if mods[mod[i]] == "Main"]
depth = np.full(n, -1, np.int32)
par = np.full(n, -1, np.int32)
bfs = []
queue = collections.deque(roots)
for r in roots:
    depth[r] = 0
while queue:
    u = queue.popleft()
    bfs.append(u)
    for v in d_sorted[ptr[u]:ptr[u + 1]]:
        if depth[v] < 0:
            depth[v] = depth[u] + 1
            par[v] = u
            queue.append(v)
reach_mask = depth >= 0
reach = int(reach_mask.sum())

# subtree size in the BFS tree (decls first found through this node, itself included)
sub = np.ones(n, np.int64)
for v in reversed(bfs):
    p = par[v]
    if p >= 0:
        sub[p] += sub[v]

# in-degree among reachable declarations ("used by N")
rs = reach_mask[src]
indeg = np.bincount(dst[rs], minlength=n)

# Euler tour of the BFS tree so that each subtree is a contiguous range
children = collections.defaultdict(list)
for v in bfs:
    if par[v] >= 0:
        children[par[v]].append(v)
tin = np.zeros(n, np.int64)
tout = np.zeros(n, np.int64)
tour = []
for r in roots:
    stack = [(r, 0)]
    tin[r] = len(tour)
    tour.append(r)
    while stack:
        u, k = stack[-1]
        ch = children.get(u, [])
        if k < len(ch):
            stack[-1] = (u, k + 1)
            c = ch[k]
            tin[c] = len(tour)
            tour.append(c)
            stack.append((c, 0))
        else:
            tout[u] = len(tour)
            stack.pop()
tour = np.array(tour, dtype=np.int64)

# folder id per declaration (first FOLDER_DEPTH path components of its module)
fnames, fix = [], {}
fol = np.zeros(n, np.int32)
mod_f = []
for m in mods:
    f = ".".join(m.split(".")[:FOLDER_DEPTH])
    if f not in fix:
        fix[f] = len(fnames)
        fnames.append(f)
    mod_f.append(fix[f])
mod_f = np.array(mod_f, np.int32)
fol = mod_f[np.array(mod, dtype=np.int64)]
NF = len(fnames)

# embedded set
S = [int(i) for i in np.where((depth >= 0) & (depth <= DMAX))[0]]
loc = {v: k for k, v in enumerate(S)}

KCODE = {"theorem": "T", "lemma": "L", "def": "D", "abbrev": "A", "structure": "S", "class": "C",
         "inductive": "I", "instance": "N", "axiom": "X", "opaque": "O"}

nodes = []
for v in S:
    deps_all = d_sorted[ptr[v]:ptr[v + 1]]
    shown = [loc[int(x)] for x in deps_all if int(x) in loc]
    shown.sort(key=lambda k: -sub[S[k]])
    hist = np.bincount(fol[tour[tin[v]:tout[v]]], minlength=NF)
    top = np.argsort(-hist)[:TOPF]
    folders = [[fnames[int(f)], int(hist[f])] for f in top if hist[f] > 0]
    nodes.append({
        "n": names[v], "k": KCODE.get(kinds[v], "?"), "m": mod[v], "l": line[v], "nl": nl[v],
        "d": int(depth[v]), "sub": int(sub[v]), "ub": int(indeg[v]),
        "dep": shown, "more": int(len(deps_all) - len(shown)),
        "tree": [loc[c] for c in children.get(v, []) if c in loc],
        "fo": folders,
    })
    # first-found parent marker: which shown deps are BFS children (solid) vs cross edges
used_mods = sorted({nd["m"] for nd in nodes})
mmap = {m: i for i, m in enumerate(used_mods)}
for nd in nodes:
    nd["m"] = mmap[nd["m"]]

# structures / classes
parents = D["parents"]
is_struct = [i for i, k in enumerate(kinds) if k in ("structure", "class")]
pmap = {int(sid): ps for sid, ps in parents}
involved = set(pmap)
for ps in pmap.values():
    for p in ps:
        if isinstance(p, int):
            involved.add(p)
sn = {}
ext_counter = collections.Counter()
for i in involved:
    ps = pmap.get(i, [])
    for p in ps:
        if isinstance(p, str):
            ext_counter[p] += 1
    sn[i] = {
        "n": names[i], "k": KCODE.get(kinds[i], "?"), "m": mods[mod[i]], "l": line[i],
        "r": bool(reach_mask[i]), "p": ps,
    }

sha = subprocess.run(["git", "-C", os.path.join(BASE, "data", "archive"), "rev-parse", "HEAD"],
                     capture_output=True, text=True).stdout.strip()

meta = {
    "decls": n, "reach": reach, "dmax": DMAX, "maxdepth": int(depth.max()), "sha": sha,
    "levels": np.bincount(depth[reach_mask]).tolist(),
    "embedded": len(S), "structures": len(is_struct),
    "structures_reachable": int(sum(1 for i in is_struct if reach_mask[i])),
    "extends_relations": len(pmap), "folder_depth": FOLDER_DEPTH,
}
route = {
    "meta": meta,
    "roots": [loc[r] for r in roots],
    "mods": [mods[i] for i in used_mods],
    "nodes": nodes,
    "structs": {"nodes": {str(k): v for k, v in sn.items()},
                "external": ext_counter.most_common(40)},
}
path = os.path.join(OUT, "route.json")
with open(path, "w", encoding="utf-8") as f:
    json.dump(route, f, ensure_ascii=False, separators=(",", ":"))
print(meta)
print("embedded nodes", len(nodes), "route.json", os.path.getsize(path) // 1024, "KB")
