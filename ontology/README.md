# Ontology Source Audit

`validate_sources.py` checks the local Turtle source closure against the
recorded manifest, merge report and merged RDF graph. It is read-only: it
never rewrites the original source, `merged.ttl`, `manifest.json` or
`merge_report.json`.

From the repository root:

```powershell
uv pip install --python .venv/Scripts/python.exe -r ontology/requirements.txt
.\.venv\Scripts\python.exe -m ontology.validate_sources
.\.venv\Scripts\python.exe -m ontology.validate_sources --json
```

The default audit compares file names, Turtle parseability, root ontology
versions and license declarations, merged counts, class conflicts, named
triples and local blank-node structure. The structural comparison is fast but
is not a formal proof of RDF isomorphism. `--deep` adds an exact isomorphism
check; on this graph it may take several minutes or longer. Exit code 0 means
the selected checks passed; exit code 1 means at least one mismatch was found.
Warnings are informative and do not change the exit code.

## Audit Findings (2026-10-21)

- All 51 filenames in `merge_report.json` are present and parseable: 49 files
  under `sources/bto/` and two BattINFO source files. The extra
  `sources/domain-battery-0.20.2.ttl` is a historical import header and is not
  part of the recorded merge closure.
- Current source union: 65,882 triples, 4,725 classes, 310 object properties,
  101 annotation properties. Recorded merge/manifest: 65,863 triples, 4,725
  classes, 310 object properties, 100 annotation properties. The stored
  `merged.ttl` fails the structural comparison against current sources.
- `sources/battinfo.ttl` declares version 0.7.0 and Apache-2.0. The manifest
  records BattINFO 0.8.0-beta and claims CC BY 4.0 for all sources; the stored
  merged graph contains the recorded 0.8.0-beta IRI and different
  ontology metadata. This is a source-snapshot mismatch, not a mere count
  formatting issue. The separate `sources/battinfo-repo/` checkout also
  declares Apache-2.0 for its software.
- `manifest.json` documents 45 originally fetched BTO files. The current
  directory contains 49 after the domain-battery update. These are different
  points in the recorded source history, not 4 missing files.
- Historical references to `ontology/NOTES.md` and `ontology/map.md` are not
  present in this checkout. Their claims should be verified against retained
  source files, reports and version control.

The audit intentionally leaves the mismatch in place. Before ontology
mapping or runtime integration, choose and pin the intended BattINFO source
version, review its source declarations and reuse obligations, then rebuild
and compare the merge in an isolated location. Do not run
`ontology/build_merged.py` against the repository baseline until that decision
is made: its current `main()` overwrites `merged.ttl` and `merge_report.json`.
The ontology source directory is currently untracked in this checkout. A
remote clone cannot reproduce this audit until the reviewed source closure
and its provenance files are deliberately versioned; do not commit the entire
separate `sources/battinfo-repo/` software checkout by accident.
The next task is ONT-01B in `docs/PROJECT_TODO.md`.
