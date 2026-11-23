"""Key-declaration shards: every cluster with reachable decls has rows; documented decls surface; line numbers point at the declaration."""
import json
import os
import unittest

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "out")
SRC = os.path.join(os.path.dirname(OUT), "data", "archive", "src")


class Keys(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = json.load(open(os.path.join(OUT, "graph.json")))
        cls.shards = {f[:-5]: json.load(open(os.path.join(OUT, "k", f))) for f in os.listdir(os.path.join(OUT, "k"))}

    def rows(self, i):
        th = self.g["n"]["th"][i] if i != self.g["meta"]["main"] else "main"
        return self.shards[str(th)], self.shards[str(th)]["n"].get(str(i), [])

    def test_every_cluster_has_rows(self):
        miss = [i for i in range(self.g["meta"]["nodes"]) if not self.rows(i)[1]]
        self.assertEqual(miss, [])

    def test_documented_decls_surface_with_doc(self):
        docs = [r for sh in self.shards.values() for rows in sh["n"].values() for r in rows if r[4]]
        self.assertGreaterEqual(len({r[0] for r in docs}), 6)

    def test_line_points_at_declaration(self):
        sh, rows = self.rows(self.g["meta"]["main"])
        r = next(r for r in rows if r[0] == "riemannHypothesis")
        path = os.path.join(SRC, *sh["m"][r[1]].split(".")) + ".lean"
        line = open(path, encoding="utf-8").read().split("\n")[r[2] - 1]
        self.assertIn("riemannHypothesis", line)


if __name__ == "__main__":
    unittest.main()
