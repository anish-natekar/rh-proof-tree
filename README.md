# rh-proof-tree

An interactive, single-page map of the Lean 4 formalization of the Riemann hypothesis
(community mirror [Deicyde/riemann-hypothesis](https://github.com/Deicyde/riemann-hypothesis),
commit `9c9f665ed79ce0fa8da61bd803b7a4bf1ad62ed0`). The goal: let a human glance at a
~150k-file, ~21M-line codebase and see its shape.

**Live site:** https://anish-natekar.github.io/rh-proof-tree/

Three views:

- **Proof route** – declaration-level dependency tree starting from the five `Main` theorems.
- **Folders** – module/folder tree with size, theorem counts, proof depth from `Main`, and
  top dependencies in and out.
- **Structures** – `structure` / `class` declarations and their `extends` hierarchy.

All names are mechanical: real Lean module and declaration names, nothing generated.

## Disclaimer

Unofficial, independent, and **not affiliated** with the authors of the formalization.
This is **not a verification** of the proof. It is a static text parse (no Lean elaboration):

- Edges are *mentions* of a declaration name, resolved with namespace / `open` scoping.
  Dot-notation, field access and instance resolution are not followed.
- About 0.5% of names are duplicates and are resolved heuristically.
- Counts are approximate.
- The data reflects the community `main` branch, not the original release.

## Rebuild

Needs `git`, `python3` (>= 3.9) and `numpy`. Needs ~2 GB of disk for the archive clone.

```bash
make        # clones the archive into data/, parses it (~1 min), writes docs/index.html
```

Pipeline (`scripts/`): `extract_modules.py` → `build_tree.py`; `extract_decls.py` →
`build_route.py`; `render_html.py` injects the JSON into `web/template.html`.
`data/` and `out/` are git-ignored; `docs/` is what GitHub Pages serves.
