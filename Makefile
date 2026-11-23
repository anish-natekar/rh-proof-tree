# Rebuild the static site from the Lean archive. Needs git, python3 (>=3.9) and numpy.
ARCHIVE_URL = https://github.com/Deicyde/riemann-hypothesis.git

.PHONY: all fetch site clean
all: site

fetch:
	@test -d data/archive/src || git clone --depth 1 $(ARCHIVE_URL) data/archive

out/modules.jsonl.gz: fetch scripts/extract_modules.py
	python3 scripts/extract_modules.py

out/tree.json: out/modules.jsonl.gz scripts/build_tree.py
	python3 scripts/build_tree.py

out/decls.json.gz out/edges.npz: out/modules.jsonl.gz scripts/extract_decls.py
	python3 scripts/extract_decls.py

out/route.json: out/decls.json.gz out/edges.npz scripts/build_route.py
	python3 scripts/build_route.py

out/rh-proof-tree.html: out/tree.json out/route.json web/template.html scripts/render_html.py
	python3 scripts/render_html.py

site: out/rh-proof-tree.html
	mkdir -p docs
	cp out/rh-proof-tree.html docs/index.html
	touch docs/.nojekyll

clean:
	rm -rf out docs/index.html
