#!/usr/bin/env python3
"""Inject out/tree.json and out/route.json into web/template.html -> out/rh-proof-tree.html."""
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tpl = open(os.path.join(BASE, "web", "template.html"), encoding="utf-8").read()


def load(name):
    s = open(os.path.join(BASE, "out", name), encoding="utf-8").read()
    return s.replace("</", "<\\/")  # keep </script> inside JSON from closing the tag


assert "__DATA__" in tpl and "__ROUTE__" in tpl
assert "/*__GRAPH_CSS__*/" in tpl and "/*__GRAPH_JS__*/" in tpl
import json

sha = json.load(open(os.path.join(BASE, "out", "route.json"), encoding="utf-8"))["meta"]["sha"]
assert len(sha) == 40, "archive commit sha missing from route.json"
tpl = tpl.replace("__SHA_SHORT__", sha[:9]).replace("__SHA__", sha)
def web(name):
    return open(os.path.join(BASE, "web", name), encoding="utf-8").read()


tpl = tpl.replace("/*__GRAPH_CSS__*/", web("graph.css")).replace("/*__GRAPH_JS__*/", web("graph.js").replace("</script", "<\\/script"))
out = tpl.replace("__DATA__", load("tree.json")).replace("__ROUTE__", load("route.json"))
path = os.path.join(BASE, "out", "rh-proof-tree.html")
open(path, "w", encoding="utf-8").write(out)
print(path, os.path.getsize(path) // 1024, "KB")
