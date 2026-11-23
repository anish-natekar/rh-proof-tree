#!/usr/bin/env python3
"""Cluster graph + precomputed radial layout for the canvas view.

Tree of clusters = module-path prefixes (<= LEVEL_MAX parts) of every module that has at least one
declaration reachable from Main. A module that is also a prefix of deeper modules gets a synthetic
child "(module)" so every graph edge ends on a leaf. Edges: reachable declaration mentions,
aggregated to leaf-cluster pairs (the viewer maps them to whatever is currently visible).

Layout (no physics in the browser):
  angle  = folder hierarchy: each node owns a wedge, children share the parent's wedge in
           proportion to the screen area their leaves need, ordered by the angle of their dependency neighbours
  radius = rho(proof depth): minimum BFS distance from the Main theorems
  then a per-level collision pass nudges overlapping nodes apart.

Output: out/graph.json (columnar arrays).
"""
import collections
import gzip
import json
import math
import os

import numpy as np
from scipy.spatial import cKDTree

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
LEVEL_MAX = 4
SWEEPS = 3
TOP = -1

D = json.load(gzip.open(os.path.join(OUT, "decls.json.gz"), "rt"))
E = np.load(os.path.join(OUT, "edges.npz"))
names, kinds, mod, mods = D["names"], D["kinds"], np.array(D["mod"]), D["mods"]
n = len(names)
src, dst = E["src"], E["dst"]

# ---------------------------------------------------------------- BFS depth from the Main decls
order = np.argsort(src, kind="stable")
s_sorted, d_sorted = src[order], dst[order]
ptr = np.searchsorted(s_sorted, np.arange(n + 1))
depth = np.full(n, -1, np.int32)
front = np.array([i for i in range(n) if mods[mod[i]] == "Main"], dtype=np.int64)
depth[front] = 0
level = 0
while len(front):
    st, en = ptr[front], ptr[front + 1]
    cnt = en - st
    tot = int(cnt.sum())
    if tot == 0:
        break
    idx = np.repeat(st - (np.cumsum(cnt) - cnt), cnt) + np.arange(tot)
    nb = d_sorted[idx]
    nb = np.unique(nb[depth[nb] < 0])
    level += 1
    depth[nb] = level
    front = nb
reach = depth >= 0
print("reachable", int(reach.sum()), "max depth", int(depth.max()))

# ---------------------------------------------------------------- per-module aggregates
CAT = {"theorem": 0, "lemma": 0, "def": 1, "abbrev": 1, "structure": 2, "class": 2, "inductive": 2, "instance": 3}
cat = np.array([CAT.get(k, 1) for k in kinds], dtype=np.int64)
nm = len(mods)
mw = np.bincount(mod[reach], minlength=nm)                       # reachable decls per module
mt = np.bincount(mod, minlength=nm)                              # all decls per module
mk = np.bincount(mod[reach] * 4 + cat[reach], minlength=nm * 4).reshape(nm, 4)
BIG = 10 ** 6
dmin = np.full(nm, BIG, np.int64)
np.minimum.at(dmin, mod[reach], depth[reach])
dsum = np.bincount(mod[reach], weights=depth[reach], minlength=nm)

# ---------------------------------------------------------------- cluster tree
node_key = {}          # tuple(parts) -> id
N = {"name": [], "p": [], "lv": [], "w": [], "wt": [], "md": [], "ds": [], "k": [], "own": [], "full": []}


def new_node(key, name, parent, lv):
    i = len(N["name"])
    node_key[key] = i
    N["name"].append(name)
    N["p"].append(parent)
    N["lv"].append(lv)
    N["w"].append(0)
    N["wt"].append(0)
    N["md"].append(BIG)
    N["ds"].append(0.0)
    N["k"].append([0, 0, 0, 0])
    N["own"].append(0)
    N["full"].append(".".join(key))
    return i


active = [m for m in range(nm) if mw[m] > 0]
parts_of = {m: mods[m].split(".")[:LEVEL_MAX] for m in active}
for m in sorted(active, key=lambda m: mods[m]):
    parts = parts_of[m]
    for l in range(1, len(parts) + 1):
        key = tuple(parts[:l])
        if key not in node_key:
            new_node(key, parts[l - 1], node_key[key[:-1]] if l > 1 else TOP, l)

has_kids = collections.Counter(p for p in N["p"] if p != TOP)
leaf_of_mod = np.full(nm, -1, np.int64)
for m in active:
    key = tuple(parts_of[m])
    i = node_key[key]
    if has_kids[i]:  # module is also a directory prefix: its own declarations live in a synthetic child
        skey = key + ("(module)",)
        if skey not in node_key:
            new_node(skey, "(module)", i, len(key) + 1)
        i = node_key[skey]
    leaf_of_mod[m] = i
    j = i
    while j != TOP:
        N["w"][j] += int(mw[m])
        N["wt"][j] += int(mt[m])
        N["md"][j] = min(N["md"][j], int(dmin[m]))
        N["ds"][j] += float(dsum[m])
        for c in range(4):
            N["k"][j][c] += int(mk[m][c])
        j = N["p"][j]
    N["own"][i] += int(mw[m])
NN = len(N["name"])
P = np.array(N["p"])
LV = np.array(N["lv"])
W = np.array(N["w"], dtype=np.float64)
MD = np.array(N["md"])
print("cluster nodes", NN, "by level", collections.Counter(N["lv"]))

kids = collections.defaultdict(list)
for i in range(NN):
    kids[N["p"][i]].append(i)
MAIN = node_key[("Main",)]
kids[TOP] = [i for i in kids[TOP] if i != MAIN]
kids[TOP].sort(key=lambda i: -W[i])
for p in list(kids):
    if p != TOP:
        kids[p].sort(key=lambda i: N["name"][i])
THEORIES = [N["name"][i] for i in kids[TOP]]
TH = np.zeros(NN, np.int32)
for ti, i in enumerate(kids[TOP]):
    stack = [i]
    while stack:
        j = stack.pop()
        TH[j] = ti
        stack.extend(kids.get(j, []))
TH[MAIN] = -1

# ---------------------------------------------------------------- leaf-cluster edges
mask = reach[src]
a = leaf_of_mod[mod[src[mask]]]
b = leaf_of_mod[mod[dst[mask]]]
assert (a >= 0).all() and (b >= 0).all()
cross = a != b
intra = int((~cross).sum())
key = a[cross] * NN + b[cross]
uk, uc = np.unique(key, return_counts=True)
EA, EB, EW = uk // NN, uk % NN, uc
print("leaf edge pairs", len(uk), "weight", int(uc.sum()), "intra-cluster", intra)

# ---------------------------------------------------------------- layout
# Organic circle-packing layout, no depth rings:
#   * every cluster reserves a disc LR (leaves: LEAFR; parents: enough area for all children),
#   * the level-2 clusters (+ Main pinned at the origin) are placed by a force layout: dependency edges
#     pull, same-theory clusters cohere, discs never overlap,
#   * children of an opened cluster are force-laid-out inside the parent's disc, pulled towards the
#     clusters they depend on / are used by.
GAP = 1.0
DENS = 0.4
LEAFR = 1.5 + 0.7 * np.log2(1 + W)
LEAFR[MAIN] = 12.0
print("main kids", kids.get(MAIN))
assert not kids.get(MAIN)

LR = np.zeros(NN)
for l in range(LEVEL_MAX, 0, -1):
    for i in np.where(LV == l)[0]:
        ch = kids.get(int(i))
        LR[i] = LEAFR[i] if not ch else math.sqrt(sum((LR[c] + GAP / 2) ** 2 for c in ch) / DENS)
LR[MAIN] = 12.0


def anc_at(l):
    a = np.arange(NN)
    for _ in range(LEVEL_MAX):
        a = np.where(LV[a] > l, P[a], a)
    return a


ANC2 = anc_at(2)
ITEMS = [MAIN] + [c for t in kids[TOP] for c in (kids.get(t) or [t])]
ITEM_IDX = {int(i): k for k, i in enumerate(ITEMS)}
GROUP = np.array([-1 if i == MAIN else TH[i] for i in ITEMS])

X = np.zeros(NN)
Y = np.zeros(NN)


def norm_w(w):
    w = np.asarray(w, dtype=np.float64)
    return (w / w.max()) ** 0.45 if len(w) and w.max() > 0 else w


def collide(pos, rr, pin=None, passes=1, bound=None, rng=None):
    n = len(pos)
    for _ in range(passes):
        pr = cKDTree(pos).query_pairs(2 * rr.max() + GAP, output_type="ndarray")
        if len(pr):
            i, j = pr[:, 0], pr[:, 1]
            d = pos[i] - pos[j]
            dist = np.hypot(d[:, 0], d[:, 1])
            ov = rr[i] + rr[j] + GAP - dist
            m = ov > 0
            if m.any():
                i, j, d, dist, ov = i[m], j[m], d[m], dist[m], ov[m]
                z = dist < 1e-6
                if z.any():
                    a = rng.uniform(0, 2 * math.pi, int(z.sum()))
                    d[z, 0], d[z, 1], dist[z] = np.cos(a), np.sin(a), 1.0
                mi, mj = rr[i] ** 1.5, rr[j] ** 1.5          # heavy discs move less: hubs stay central
                fi, fj = (mj / (mi + mj))[:, None], (mi / (mi + mj))[:, None]
                u = d / dist[:, None] * ov[:, None]
                mv = np.zeros_like(pos); ct = np.zeros(n)
                np.add.at(mv, i, u * fi); np.add.at(mv, j, -u * fj)
                np.add.at(ct, i, 1); np.add.at(ct, j, 1)
                pos += 1.1 * mv / np.maximum(ct, 1)[:, None]
        if pin is not None:
            pos[pin] = 0.0
        if bound is not None:
            nr = np.hypot(pos[:, 0], pos[:, 1])
            lim = np.maximum(bound - rr, 0.0)
            f = np.where(nr > lim, lim / np.maximum(nr, 1e-9), 1.0)
            pos *= f[:, None]


def force_layout(rr, ea, eb, ew, init, pin=None, group=None, ext=None, bound=None, iters=300, seed=0, GRAV=0.02):
    """rr: radii. ea/eb/ew: sparse edges (local ids). init: (n,2). ext: (n,2) unit-ish direction pull."""
    rng = np.random.default_rng(seed)
    pos = init.copy().astype(np.float64)
    n = len(pos)
    if pin is not None:
        pos[pin] = 0.0
    if n == 1:
        return pos
    nw = norm_w(ew)
    S = np.zeros(n)
    if len(ea):
        np.add.at(S, ea, nw); np.add.at(S, eb, nw)
    for t in range(iters):
        al = 0.35 * (1 - t / iters) + 0.03
        if len(ea):
            d = pos[eb] - pos[ea]
            dist = np.hypot(d[:, 0], d[:, 1]) + 1e-9
            st = np.maximum(dist - (rr[ea] + rr[eb] + GAP), 0)
            f = (nw * st / dist)[:, None] * d
            mv = np.zeros_like(pos)
            np.add.at(mv, ea, f); np.add.at(mv, eb, -f)
            pos += al * mv / (S[:, None] + 1.0)
        if group is not None:
            for g in np.unique(group[group >= 0]):
                mk = group == g
                c = np.average(pos[mk], axis=0, weights=rr[mk] ** 2)
                pos[mk] += 0.10 * al * (c - pos[mk])
        if ext is not None:
            pos += 0.25 * al * (ext - pos)
        pos *= 1 - GRAV * al          # gravity
        collide(pos, rr, pin, 1, bound, rng)
    collide(pos, rr, pin, 400 if n < 400 else 2500, bound, rng)
    return pos


# ---- top level: greedy circle packing around Main
def greedy_pack(rr, ea, eb, ew, group, pin=0):
    """Place discs one by one: the unplaced disc most strongly linked to the placed set goes next, at the
    free spot closest to the weighted centroid of its placed neighbours (+ its theory + the origin)."""
    n = len(rr)
    nw = np.log1p(ew)
    adj = [[] for _ in range(n)]
    for a, b, w in zip(ea, eb, nw):
        adj[a].append((b, w)); adj[b].append((a, w))
    pos = np.zeros((n, 2))
    placed = np.zeros(n, bool)
    placed[pin] = True
    attach = np.zeros(n)
    for b, w in adj[pin]:
        attach[b] += w
    gs, gc = {}, {}
    for _ in range(n - 1):
        cand = np.where(~placed)[0]
        i = int(cand[np.argmax(attach[cand] + 1e-7 * rr[cand])])
        tp, tw = np.zeros(2), 0.0
        for j, w in adj[i]:
            if placed[j]:
                tp += w * pos[j]; tw += w
        g = group[i]
        wg = (0.6 * tw if tw > 0 else 1.0)
        if g >= 0 and gc.get(g, 0):
            tp += wg * gs[g] / gc[g]; tw += wg
        wo = 0.1 * tw + 0.02
        tw += wo
        tgt = tp / tw
        P_, R_ = pos[placed], rr[placed]
        st = max(rr[i] / 3.0, 3.0)
        dmax = 8 * st
        while True:
            ds, an = [], []
            for d in np.arange(0.0, dmax, st):
                k = 1 if d == 0 else int(min(180, max(8, 2 * math.pi * d / st)))
                ds.append(np.full(k, d)); an.append(np.linspace(0, 2 * math.pi, k, endpoint=False) + d * 0.37)
            ds, an = np.concatenate(ds), np.concatenate(an)
            c = np.c_[tgt[0] + ds * np.cos(an), tgt[1] + ds * np.sin(an)]
            ok = np.ones(len(c), bool)
            for s0 in range(0, len(c), 4000):
                cc = c[s0:s0 + 4000]
                dd = np.hypot(cc[:, None, 0] - P_[None, :, 0], cc[:, None, 1] - P_[None, :, 1])
                ok[s0:s0 + 4000] = (dd >= (R_[None, :] + rr[i] + GAP)).all(1)
            if ok.any():
                dfirst = ds[ok].min()
                sel = ok & (ds <= dfirst + max(2 * rr[i], 15.0))
                cost = ds + 0.3 * np.hypot(c[:, 0], c[:, 1])
                cost[~sel] = 1e18
                best = int(np.argmin(cost))
                pos[i] = c[best]
                break
            dmax *= 2
        placed[i] = True
        for j, w in adj[i]:
            attach[j] += w
        if g >= 0:
            gs[g] = gs.get(g, 0) + pos[i]; gc[g] = gc.get(g, 0) + 1
    return pos


m_ = ANC2[EA] != ANC2[EB]
pairs = np.c_[np.minimum(ANC2[EA][m_], ANC2[EB][m_]), np.maximum(ANC2[EA][m_], ANC2[EB][m_])]
upr, inv = np.unique(pairs, axis=0, return_inverse=True)
uw = np.bincount(inv.ravel(), weights=EW[m_].astype(np.float64))
ea0 = np.array([ITEM_IDX[int(a)] for a in upr[:, 0]]); eb0 = np.array([ITEM_IDX[int(b)] for b in upr[:, 1]])
rrt = LR[ITEMS]
pos0 = greedy_pack(rrt, ea0, eb0, uw, GROUP)
X[ITEMS], Y[ITEMS] = pos0[:, 0], pos0[:, 1]

# ---- external direction per node (toward the other slots it talks to), aggregated up the tree
VX = np.zeros(NN); VY = np.zeros(NN)
mm = ANC2[EA] != ANC2[EB]
a_, b_, w_ = EA[mm], EB[mm], np.log1p(EW[mm].astype(np.float64))
for (u, v) in ((a_, b_), (b_, a_)):
    dx = X[ANC2[v]] - X[ANC2[u]]; dy = Y[ANC2[v]] - Y[ANC2[u]]
    dd = np.hypot(dx, dy) + 1e-9
    np.add.at(VX, u, w_ * dx / dd); np.add.at(VY, u, w_ * dy / dd)
for l in range(LEVEL_MAX, 2, -1):
    for i in np.where(LV == l)[0]:
        VX[P[i]] += VX[i]; VY[P[i]] += VY[i]

# ---- sibling edges per parent for levels 3, 4
sib = {}
for l in (3, 4):
    al_ = anc_at(l)
    m = (al_[EA] != al_[EB]) & (P[al_[EA]] == P[al_[EB]])
    if not m.any():
        continue
    aa, bb = np.minimum(al_[EA][m], al_[EB][m]), np.maximum(al_[EA][m], al_[EB][m])
    key = aa.astype(np.int64) * NN + bb
    uk2, iv = np.unique(key, return_inverse=True)
    uw2 = np.bincount(iv.ravel(), weights=EW[m].astype(np.float64))
    pa, pb = uk2 // NN, uk2 % NN
    for a, b, w in zip(pa, pb, uw2):
        sib.setdefault(int(P[a]), []).append((int(a), int(b), float(w)))

# ---- top-down: lay children inside the parent disc
for p in sorted([i for i in range(NN) if kids.get(i) and LV[i] >= 2], key=lambda i: LV[i]):
    ch = np.array(kids[p])
    idx = {int(c): k for k, c in enumerate(ch)}
    es = sib.get(int(p), [])
    ea = np.array([idx[a] for a, b, w in es], dtype=np.int64)
    eb = np.array([idx[b] for a, b, w in es], dtype=np.int64)
    ew = np.array([w for a, b, w in es], dtype=np.float64)
    rr = LR[ch]
    Rb = LR[p]
    v = np.c_[VX[ch], VY[ch]]
    vn = np.hypot(v[:, 0], v[:, 1])
    ext = np.where(vn[:, None] > 0, v / np.maximum(vn, 1e-9)[:, None] * Rb * 0.45, 0.0)
    ga = math.pi * (3 - math.sqrt(5))
    order_ = np.argsort(-rr, kind="stable")
    init = np.zeros((len(ch), 2))
    for rank, k in enumerate(order_):
        rad = Rb * 0.9 * math.sqrt((rank + 0.5) / len(ch))
        init[k] = (rad * math.cos(rank * ga), rad * math.sin(rank * ga))
    init = 0.5 * init + 0.5 * ext
    loc = force_layout(rr, ea, eb, ew, init, ext=None if not (vn > 0).any() else ext, bound=Rb, iters=160 if len(ch) > 400 else 240, seed=int(p))
    X[ch], Y[ch] = X[p] + loc[:, 0], Y[p] + loc[:, 1]

# theory nodes: centroid of their items
for t in kids[TOP]:
    its = kids.get(t) or [t]
    X[t] = float(np.average(X[its], weights=LR[its] ** 2)); Y[t] = float(np.average(Y[its], weights=LR[its] ** 2))
X[MAIN] = Y[MAIN] = 0.0

# display radius: leaves keep LEAFR, parents shrink sub-linearly so the overview is not dominated by giants
NR = np.where(LR <= 60, LR, 60 * (LR / 60) ** 0.6)
NR = np.where([bool(kids.get(i)) for i in range(NN)], NR, LEAFR)
NR[MAIN] = 12.0

# ---------------------------------------------------------------- write
order_e = np.argsort(-EW, kind="stable")
meta = {
    "sha": json.load(open(os.path.join(OUT, "route.json"), encoding="utf-8"))["meta"]["sha"],
    "nodes": NN,
    "main": int(MAIN),
    "theories": THEORIES,
    "level_max": LEVEL_MAX,
    "reach": int(reach.sum()),
    "max_depth": int(depth.max()),
    "edge_pairs": int(len(uk)),
    "edge_weight": int(EW.sum()),
    "intra_edges": intra,
}
g = {
    "meta": meta,
    "n": {
        "name": N["name"],
        "p": N["p"],
        "lv": N["lv"],
        "th": TH.tolist(),
        "w": N["w"],
        "wt": N["wt"],
        "md": [m if m < BIG else -1 for m in N["md"]],
        "ds": [round(d / max(w, 1), 1) for d, w in zip(N["ds"], N["w"])],
        "k": [v for row in N["k"] for v in row],
        "own": N["own"],
        "x": [round(float(v), 1) for v in X],
        "y": [round(float(v), 1) for v in Y],
        "r": [round(float(v), 1) for v in NR],
        "lr": [round(float(v), 1) for v in LR],
    },
    "e": np.c_[EA[order_e], EB[order_e], EW[order_e]].ravel().tolist(),
}
path = os.path.join(OUT, "graph.json")
with open(path, "w") as f:
    json.dump(g, f, separators=(",", ":"))
print(path, os.path.getsize(path) // 1024, "KB")
