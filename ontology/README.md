# Ontology Source Audit

`validate_sources.py` checks the local Turtle source closure against the
pinned SHA-256 hashes, manifest, merge report and merged RDF graph. It is read-only: it
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

## Reconciled Snapshot (2026-10-21)

- All 51 filenames in `merge_report.json` are present and parseable: 49 files
  under `sources/bto/` and two BattINFO source files. The extra
  `sources/domain-battery-0.20.2.ttl` is a historical import header and is not
  part of the recorded merge closure.
- The pinned union has 65,882 triples, 4,725 classes, 310 object properties
  and 101 annotation properties. The manifest, report and merged graph now
  agree with the 51 local source files. All 51 source bytes are SHA-256-pinned
  in `manifest.json`.
- The locally available `sources/battinfo.ttl` is byte-identical to the
  separate BattINFO checkout and declares 0.7.0/Apache-2.0. The previous
  merged artifact declared 0.8.0-beta/CC BY 4.0, but its original source
  file and authenticated commit are not available here. This is a new curated
  baseline, not a reproduction of that older BattINFO source. The previous
  graph and report are preserved under `history/`.
- Six root ontologies declare CC BY 4.0 and BattINFO declares Apache-2.0.
  Keep source-level attribution and review redistribution requirements before
  publishing this mixed-source graph. Do not describe every source as CC BY.
- BattINFO 0.7.0 imports electrochemistry 0.37.2 and chemical-substance 0.15.0,
  while this union includes 0.31.1 and 0.12.3. The merge builder does not
  resolve `owl:imports`; ontology mapping must not assume a fully compatible
  transitive dependency closure. This is an explicit ONT-02 review item.
- `manifest.json` documents 45 originally fetched BTO files. The current
  directory contains 49 after the domain-battery update. These are different
  points in the recorded source history, not 4 missing files.
- Historical references to `ontology/NOTES.md` and `ontology/map.md` are not
  present in this checkout. Their claims should be verified against retained
  source files, reports and version control.

To reproduce the merge without changing the baseline, run
`python ontology/build_merged.py --output-dir <temporary-directory>` and
compare its two outputs. Running the builder without `--output-dir` still
overwrites the default artifacts. The curated source files and provenance
artifacts must be committed together for a remote clone to reproduce this
audit. Do not commit the entire separate `sources/battinfo-repo/` checkout.
See `docs/PROJECT_TODO.md` for the next mapping step.
