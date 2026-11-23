#!/usr/bin/env python3
"""Static scan of the Lean archive source tree.

No Lean elaboration. For every .lean file under src/ record:
  - module name (from path)
  - imports (import / public import / private import / meta import)
  - line count
  - declarations found by line-start regex (name + kind + line)

Output: out/modules.jsonl.gz  (one JSON object per module)
"""
import bisect
import gzip
import json
import os
import re
import sys
from multiprocessing import Pool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "archive", "src")
OUT = os.path.join(ROOT, "out")

IMPORT_RE = re.compile(r"^(?:(?:public|private|meta)\s+)*import\s+([^\s]+)", re.M)
DECL_RE = re.compile(
    r"^[ \t]*(?:@\[[^\]\n]*\][ \t]*)*"
    r"(?:(?:private|protected|noncomputable|public|unsafe|partial|nonrec|meta)[ \t]+)*"
    r"(theorem|lemma|def|abbrev|structure|class|inductive|instance|axiom|opaque)"
    r"[ \t]+([^\s:({\[]+)?",
    re.M,
)


def modname(path: str) -> str:
    rel = os.path.relpath(path, SRC)
    return rel[:-5].replace(os.sep, ".")


def scan(path: str):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    head = "\n".join(text.split("\n", 3000)[:3000])
    imports = sorted(set(IMPORT_RE.findall(head)))
    decls = []
    for m in DECL_RE.finditer(text):
        kind, name = m.group(1), m.group(2)
        decls.append((kind, name or "", m.start()))
    # convert char offsets to line numbers
    if decls:
        line_starts = [0]
        for m in re.finditer("\n", text):
            line_starts.append(m.end())
        decls = [(k, n, bisect.bisect_right(line_starts, off)) for k, n, off in decls]
    return {
        "m": modname(path),
        "imp": imports,
        "loc": text.count("\n") + 1,
        "d": decls,
    }


def main():
    os.makedirs(OUT, exist_ok=True)
    files = []
    for root, _, names in os.walk(SRC):
        for n in names:
            if n.endswith(".lean"):
                files.append(os.path.join(root, n))
    files.sort()
    print(f"{len(files)} files", file=sys.stderr)
    out_path = os.path.join(OUT, "modules.jsonl.gz")
    n = 0
    with Pool() as pool, gzip.open(out_path, "wt", encoding="utf-8") as out:
        for rec in pool.imap(scan, files, chunksize=200):
            if rec is None:
                continue
            out.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
            n += 1
            if n % 20000 == 0:
                print(f"  {n}", file=sys.stderr)
    print(f"wrote {n} modules -> {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
