"""M1: layout / aggregation invariants of out/graph.json."""
import json
import math
import os
import unittest

import numpy as np

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "out")


class Graph(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(OUT, "graph.json")) as f:
            g = json.load(f)
        cls.m, cls.n = g["meta"], g["n"]
        cls.e = np.array(g["e"]).reshape(-1, 3)
        cls.N = cls.m["nodes"]

    def test_columns_same_length(self):
        for k, v in self.n.items():
            if k == "k":
                self.assertEqual(len(v), 4 * self.N)
            else:
                self.assertEqual(len(v), self.N, k)

    def test_children_inside_parent_disc(self):
        n = self.n
        bad = 0
        for i in range(self.N):
            p = n["p"][i]
            if p < 0 or n["lv"][i] < 3:
                continue
            d = math.hypot(n["x"][i] - n["x"][p], n["y"][i] - n["y"][p])
            if d + n["lr"][i] > n["lr"][p] + 2.0:
                bad += 1
        self.assertLess(bad, 0.001 * self.N + 3)

    def test_weight_conserved(self):
        n = self.n
        s = [0] * self.N
        for i in range(self.N):
            if n["p"][i] >= 0:
                s[n["p"][i]] += n["w"][i]
        for i in range(self.N):
            self.assertEqual(n["w"][i], n["own"][i] + s[i], n["name"][i])
        total_top = sum(n["w"][i] for i in range(self.N) if n["p"][i] < 0)
        self.assertEqual(total_top, self.m["reach"])

    def test_edges_conserved(self):
        # every reachable-source edge is either cross-cluster (aggregated) or intra-cluster
        self.assertEqual(int(self.e[:, 2].sum()) + self.m["intra_edges"], self._reach_edges())

    def _reach_edges(self):
        import gzip
        D = json.load(gzip.open(os.path.join(OUT, "decls.json.gz"), "rt"))
        E = np.load(os.path.join(OUT, "edges.npz"))
        names = D["names"]
        mod = np.array(D["mod"])
        mods = D["mods"]
        # reachable = BFS from Main decls
        n = len(names)
        order = np.argsort(E["src"], kind="stable")
        s, d = E["src"][order], E["dst"][order]
        ptr = np.searchsorted(s, np.arange(n + 1))
        seen = np.zeros(n, bool)
        front = np.array([i for i in range(n) if mods[mod[i]] == "Main"])
        seen[front] = True
        while len(front):
            nb = np.concatenate([d[ptr[u]:ptr[u + 1]] for u in front]) if len(front) < 5000 else d[np.concatenate([np.arange(ptr[u], ptr[u + 1]) for u in front])]
            nb = np.unique(nb[~seen[nb]])
            seen[nb] = True
            front = nb
        return int(seen[E["src"]].sum())

    def test_linked_clusters_are_closer_than_random(self):
        n = self.n
        x, y = np.array(n["x"]), np.array(n["y"])
        lv = np.array(n["lv"])
        # level-2 view: weighted mean edge length vs. mean distance of random pairs
        anc = np.arange(self.N)
        p = np.array(n["p"])
        for _ in range(4):
            anc = np.where((lv[anc] > 2), p[anc], anc)
        a, b, w = self.e[:, 0], self.e[:, 1], self.e[:, 2]
        a, b = anc[a], anc[b]
        m = a != b
        lr = np.array(n["lr"])
        d = np.hypot(x[a[m]] - x[b[m]], y[a[m]] - y[b[m]]) - lr[a[m]] - lr[b[m]]   # surface-to-surface gap
        edge_len = float((d * w[m]).sum() / w[m].sum())
        idx = np.where(lv == 2)[0]
        rng = np.random.default_rng(0)
        i, j = rng.choice(idx, 4000), rng.choice(idx, 4000)
        k_ = i != j
        lrr = np.array(n["lr"])
        rand_len = float((np.hypot(x[i] - x[j], y[i] - y[j]) - lrr[i] - lrr[j])[k_].mean())
        self.assertLess(edge_len, 0.6 * rand_len)

    def test_no_overlap_per_level(self):
        from scipy.spatial import cKDTree
        n = self.n
        for l in (2, 3, 4):
            idx = [i for i in range(self.N) if n["lv"][i] == l]
            pts = np.c_[[n["x"][i] for i in idx], [n["y"][i] for i in idx]]
            r = np.array([n["lr"][i] for i in idx])
            pr = cKDTree(pts).query_pairs(2 * r.max(), output_type="ndarray")
            d = np.hypot(*(pts[pr[:, 0]] - pts[pr[:, 1]]).T)
            ov = (r[pr[:, 0]] + r[pr[:, 1]] - d) > 0.5
            frac = ov.sum() / max(len(idx), 1)
            self.assertLess(frac, 0.03, f"level {l}: {ov.sum()} overlapping pairs / {len(idx)} nodes")

    def test_main_center_and_theories(self):
        mi = self.m["main"]
        self.assertEqual((self.n["x"][mi], self.n["y"][mi]), (0, 0))
        self.assertIn("Development", self.m["theories"])

    def test_deterministic(self):
        import subprocess, sys, hashlib
        a = hashlib.sha1(open(os.path.join(OUT, "graph.json"), "rb").read()).hexdigest()
        subprocess.run([sys.executable, os.path.join(os.path.dirname(OUT), "scripts", "build_graph.py")], check=True, capture_output=True)
        b = hashlib.sha1(open(os.path.join(OUT, "graph.json"), "rb").read()).hexdigest()
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
