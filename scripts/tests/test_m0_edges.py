"""M0: noise filter invariants on out/edges.npz + out/decls.json.gz.  Run: python3 -m unittest discover -s scripts/tests"""
import gzip
import json
import os
import unittest

import numpy as np

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "out")


class NoiseFilter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.D = json.load(gzip.open(os.path.join(OUT, "decls.json.gz"), "rt"))
        E = np.load(os.path.join(OUT, "edges.npz"))
        cls.src, cls.dst = E["src"], E["dst"]
        cls.mod = np.array(cls.D["mod"])

    def test_no_cross_module_edge_to_single_token(self):
        single = np.array(["." not in x for x in self.D["names"]])
        bad = single[self.dst] & (self.mod[self.src] != self.mod[self.dst])
        self.assertEqual(int(bad.sum()), 0)

    def test_noise_hubs_gone(self):
        names = self.D["names"]
        ind = np.bincount(self.dst, minlength=len(names))
        top = {names[i] for i in np.argsort(-ind)[:20]}
        for w in ("hm", "first", "key", "subst", "change", "e1", "e2", "hU", "hJ"):
            self.assertNotIn(w, top)

    def test_real_hub_survives(self):
        names = self.D["names"]
        ind = np.bincount(self.dst, minlength=len(names))
        i = names.index("Formalism.BasicNotions.D7")
        self.assertGreater(ind[i], 20000)

    def test_edge_count_and_reach(self):
        self.assertEqual(len(self.src), 4356360)
        r = json.load(open(os.path.join(OUT, "route.json")))["meta"]
        self.assertEqual(r["reach"], 710915)


if __name__ == "__main__":
    unittest.main()
