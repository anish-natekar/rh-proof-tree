#!/usr/bin/env python3
"""Declaration-level static extraction (approximate; no Lean elaboration).

Pass 1: per file, track `namespace` / `section` / `end` / `open`, and record each named declaration
        with its fully-qualified name, kind, line, docstring first line and body size.
Pass 2: per declaration, tokenise signature+body, resolve identifiers against the project's own
        declaration names using the active namespaces and opens, and record  A -> B  edges.
        For structure/class also resolve `extends` parents.

Limits (shown honestly in the UI): dot-notation on local values (h.symm), structure field
projections, instance resolution and notation are NOT resolved. Edges are 'mentions', found by
name, so an edge can be a false positive on a shadowed name and many real uses are missed.

Output: out/decls.json.gz (columns) and out/edges.npz (src, dst).
"""
import bisect
import gzip
import json
import os
import re
import sys
from multiprocessing import Pool

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "archive", "src")
OUT = os.path.join(ROOT, "out")

BLOCK_COMMENT = re.compile(r"/-(-?)(.*?)-/", re.S)
LINE_COMMENT = re.compile(r"--[^\n]*")
MODS = r"(?:(?:private|protected|noncomputable|public|unsafe|partial|nonrec|meta|local)\s+)*"
DECL_HEAD = re.compile(
    r"^(?:@\[[^\n]*?\]\s*)*" + MODS +
    r"(theorem|lemma|def|abbrev|structure|class|inductive|instance|axiom|opaque)\s+([^\s:({\[]+)?"
)
NS_RE = re.compile(r"^(?:@\[[^\n]*?\]\s*)*namespace\s+(\S+)")
SEC_RE = re.compile(r"^(?:@\[[^\n]*?\]\s*)*(?:(?:noncomputable|public|private|meta)\s+)*section(?:\s+(\S+))?\s*$")
END_RE = re.compile(r"^end(?:\s+(\S+))?\s*$")
OPEN_RE = re.compile(r"^open\s+(?:scoped\s+)?(.*)", re.S)
EXT_RE = re.compile(r"\bextends\s+(.+?)(?:\s+where\b|\s*:=|\s*\n\s*\n|$)", re.S)
TOKEN_RE = re.compile(r"[^\W\d][\w'.!?]*")


def _blank_comments(text):
    """Remove comments, keep line structure. Return (clean_text, {line_index_after_doc: first_line})."""
    docs = {}
    starts = [0]
    for mm in re.finditer("\n", text):
        starts.append(mm.end())

    def repl(m):
        body = m.group(0)
        nl = body.count("\n")
        if m.group(1) == "-":  # docstring /-- ... -/
            first = m.group(2).strip().split("\n", 1)[0].strip()
            # 0-based index of the line right after the docstring's last line
            docs[bisect.bisect_right(starts, m.end() - 1)] = first[:160]
        return "\n" * nl

    clean = BLOCK_COMMENT.sub(repl, text)
    clean = LINE_COMMENT.sub("", clean)
    return clean, docs


def parse_file(path):
    """Yield dict per declaration (named or not): see keys below."""
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    clean, docs = _blank_comments(text)
    lines = clean.split("\n")
    # command blocks: start at each column-0 non-space line
    starts = [i for i, ln in enumerate(lines) if ln and not ln[0].isspace()]
    starts.append(len(lines))
    stack = []  # entries: ("ns", name) | ("sec", None); each with its own opens list
    opens_by_level = []  # parallel list of lists
    out = []
    pending_in = None
    for bi in range(len(starts) - 1):
        a, b = starts[bi], starts[bi + 1]
        head = lines[a]
        block = "\n".join(lines[a:b])
        cur_ns = ".".join(n for k, n in stack if k == "ns")
        opens = [o for lvl in opens_by_level for o in lvl]
        m = NS_RE.match(head)
        if m:
            stack.append(("ns", m.group(1)))
            opens_by_level.append([])
            continue
        if SEC_RE.match(head):
            stack.append(("sec", None))
            opens_by_level.append([])
            continue
        if END_RE.match(head):
            if stack:
                stack.pop()
                opens_by_level.pop()
            continue
        m = OPEN_RE.match(block)
        if m and head.startswith("open"):
            body = m.group(1)
            is_in = re.search(r"\bin\s*$", body.split("\n", 1)[0]) is not None or re.search(r"\bin\s*(\n|$)", body) is not None
            body = re.split(r"\bin\b", body, maxsplit=1)[0]
            body = re.sub(r"\([^)]*\)", " ", body)
            body = re.split(r"\b(?:hiding|renaming)\b", body, maxsplit=1)[0]
            names = [t for t in body.split() if re.match(r"^[^\W\d][\w'.!?]*$", t)]
            if is_in:
                pending_in = names
            else:
                if not opens_by_level:
                    opens_by_level.append([])
                opens_by_level[-1].extend(names)
            continue
        m = DECL_HEAD.match(head)
        if m:
            kind, name = m.group(1), m.group(2)
            full = None
            if name:
                name = name.rstrip(".")
                if name.startswith("_root_."):
                    full = name[7:]
                else:
                    full = (cur_ns + "." + name) if cur_ns else name
            # docstring that ended just before this block (allow attribute lines/blank)
            doc = docs.get(a) or docs.get(a + 0) or None
            if doc is None:
                for back in (0, 1, 2):
                    if (a - back) in docs:
                        doc = docs[a - back]
                        break
            cur_opens = opens + (pending_in or [])
            out.append({
                "kind": kind, "full": full, "line": a + 1, "doc": doc,
                "nl": sum(1 for ln in lines[a:b] if ln.strip()),
                "ns": cur_ns, "opens": cur_opens, "block": block,
            })
        pending_in = None
    return out


# ---------------------------------------------------------------- pass 1
FILES = []


def pass1(i):
    path = FILES[i]
    rel = os.path.relpath(path, SRC)[:-5].replace(os.sep, ".")
    try:
        ds = parse_file(path)
    except Exception as e:  # keep going, report
        return i, rel, None, repr(e)
    recs = [(d["kind"], d["full"], d["line"], d["doc"], d["nl"]) for d in ds]
    return i, rel, recs, None


# ---------------------------------------------------------------- pass 2
DECLS = {}   # full name -> id (first definition wins)
LAST = set()  # all path components of declared names (cheap prefilter)
BASE = {}    # file index -> first id of that file's named decls
_cache = {}


def resolve(tok, ns, opens):
    parts = tok.split(".")
    if not any(p in LAST for p in parts):
        return None
    key = (tok, ns, tuple(opens))
    if key in _cache:
        return _cache[key]
    res = None
    prefixes = []
    if ns:
        segs = ns.split(".")
        prefixes = [".".join(segs[:k]) for k in range(len(segs), 0, -1)]
    nvar = len(parts)
    for cut in range(nvar, 0, -1):
        v = ".".join(parts[:cut])
        if v.startswith("_root_."):
            r = DECLS.get(v[7:])
            if r is not None:
                res = r
                break
            continue
        for p in prefixes:
            r = DECLS.get(p + "." + v)
            if r is not None:
                res = r
                break
        if res is not None:
            break
        r = DECLS.get(v)
        if r is not None:
            res = r
            break
        for o in opens:
            r = DECLS.get(o + "." + v)
            if r is None:
                for p in prefixes:
                    r = DECLS.get(p + "." + o + "." + v)
                    if r is not None:
                        break
            if r is not None:
                res = r
                break
        if res is not None:
            break
    if len(_cache) > 2_000_000:
        _cache.clear()
    _cache[key] = res if res is not None else -1
    return res


DUPLIST = []  # dup code -(k+2) -> list of candidate ids
MODCOL = []   # id -> module (file) index
IMPORTS = {}  # file index -> set of directly imported file indices
AMBIG = [0]


def pick(cands, m):
    """Choose among same-named declarations: same module, direct import, import-of-import, else first."""
    for c in cands:
        if MODCOL[c] == m:
            return c
    imp = IMPORTS.get(m, ())
    for c in cands:
        if MODCOL[c] in imp:
            return c
    imp2 = set()
    for x in imp:
        imp2 |= IMPORTS.get(x, set())
    for c in cands:
        if MODCOL[c] in imp2:
            return c
    return cands[0]


def pass2(i):
    path = FILES[i]
    ds = parse_file(path)
    k = 0
    src_list, dst_list, parents = [], [], []
    for d in ds:
        if not d["full"]:
            continue
        sid = BASE[i] + k
        k += 1
        ns, opens = d["ns"], d["opens"]
        block = d["block"]
        seen = set()
        for tok in TOKEN_RE.findall(block):
            tok = tok.rstrip(".")
            if len(tok) < 2:
                continue
            r = resolve(tok, ns, opens)
            if r is None or r == -1:
                continue
            if r <= -2:
                r = pick(DUPLIST[-r - 2], i)
            if r != sid:
                seen.add(r)
        if seen:
            src_list.append(sid)
            dst_list.append(sorted(seen))
        if d["kind"] in ("structure", "class"):
            m = EXT_RE.search(block)
            if m:
                ps = []
                for part in m.group(1).split(","):
                    part = part.strip()
                    if not part:
                        continue
                    if ":" in part:  # named parent:  extends toFoo : Foo
                        part = part.split(":", 1)[1].strip()
                    first = TOKEN_RE.match(part)
                    if not first:
                        continue
                    t = first.group(0).rstrip(".")
                    r = resolve(t, ns, opens)
                    if r is not None and r <= -2:
                        r = pick(DUPLIST[-r - 2], i)
                    ps.append(r if (r is not None and r != -1) else t)
                if ps:
                    parents.append((sid, ps))
    return src_list, dst_list, parents


def main():
    global FILES, DECLS, LAST, BASE
    for root, _, names in os.walk(SRC):
        for n in names:
            if n.endswith(".lean"):
                FILES.append(os.path.join(root, n))
    FILES.sort()
    nproc = 8
    print(f"{len(FILES)} files", file=sys.stderr)

    # pass 1
    mod_of_file = [None] * len(FILES)
    per_file = [None] * len(FILES)
    errs = []
    with Pool(nproc) as pool:
        for i, rel, recs, err in pool.imap_unordered(pass1, range(len(FILES)), chunksize=100):
            mod_of_file[i] = rel
            if err:
                errs.append((rel, err))
                per_file[i] = []
            else:
                per_file[i] = recs
    print(f"pass1 done, {len(errs)} parse errors", file=sys.stderr)

    names, kinds, mods_col, lines, nls, docs = [], [], [], [], [], {}
    dup = 0
    unnamed = 0
    mod_names = []
    cands = {}  # full name -> [ids]  (Challenge.lean is a Comparator artifact: never a resolution target)
    for i, recs in enumerate(per_file):
        BASE[i] = len(names)
        mod_idx = len(mod_names)
        mod_names.append(mod_of_file[i])
        for kind, full, line, doc, nl in recs:
            if not full:
                unnamed += 1
                continue
            idx = len(names)
            names.append(full)
            kinds.append(kind)
            mods_col.append(mod_idx)
            lines.append(line)
            nls.append(nl)
            if doc:
                docs[idx] = doc
            if mod_of_file[i] == "Challenge":
                continue
            cands.setdefault(full, []).append(idx)
            for p in full.split("."):
                LAST.add(p)
    for full, ids in cands.items():
        if len(ids) == 1:
            DECLS[full] = ids[0]
        else:
            dup += len(ids) - 1
            DUPLIST.append(ids)
            DECLS[full] = -(len(DUPLIST) - 1) - 2
    MODCOL.extend(mods_col)
    m2i = {m: i for i, m in enumerate(mod_of_file)}
    for line in gzip.open(os.path.join(OUT, "modules.jsonl.gz"), "rt"):
        r = json.loads(line)
        fi = m2i.get(r["m"])
        if fi is not None:
            IMPORTS[fi] = {m2i[x] for x in r["imp"] if x in m2i}
    print(f"named decls {len(names)}, unnamed {unnamed}, extra duplicate copies {dup}", file=sys.stderr)

    # pass 2 (workers inherit DECLS/LAST/BASE via fork)
    src_all, dst_all = [], []
    parents_all = []
    with Pool(nproc) as pool:
        for n, (s, d, p) in enumerate(pool.imap(pass2, range(len(FILES)), chunksize=50)):
            for sid, dl in zip(s, d):
                src_all.extend([sid] * len(dl))
                dst_all.extend(dl)
            parents_all.extend(p)
            if n % 20000 == 0:
                print(f"  pass2 {n}", file=sys.stderr)
    print(f"edges {len(src_all)}", file=sys.stderr)

    os.makedirs(OUT, exist_ok=True)
    np.savez_compressed(os.path.join(OUT, "edges.npz"),
                        src=np.array(src_all, dtype=np.int32), dst=np.array(dst_all, dtype=np.int32))
    with gzip.open(os.path.join(OUT, "decls.json.gz"), "wt", encoding="utf-8") as f:
        json.dump({
            "names": names, "kinds": kinds, "mod": mods_col, "line": lines, "nl": nls,
            "docs": docs, "mods": mod_names, "parents": parents_all, "dup": dup,
        }, f, ensure_ascii=False, separators=(",", ":"))
    print("done", file=sys.stderr)


if __name__ == "__main__":
    main()
