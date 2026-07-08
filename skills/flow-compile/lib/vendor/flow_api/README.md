# Vendored Flow API scripts

Copies of advbfx `flowAPIscripts/` used by flow-compile delivery and post-upload
stages. Bundled so a **ClawBio-only clone** can upload, submit analysis, and edit
sample metadata without the parent advbfx tree.

## Upload / analysis / preprocessing

| Path | Upstream |
|------|----------|
| `upload/uploadsample_flowbio_v6.py` | `flowAPIscripts/upload/uploadsample_flowbio_v6.py` |
| `analysis/flowrunanalysis_flowbio.py` | `flowAPIscripts/analysis/flowrunanalysis_flowbio.py` |
| `preprocessing/removespace.py` | `flowAPIscripts/preprocessing/removespace.py` |

Resolved by `lib/script_paths.resolve_flow_script()` (vendor copy first, then advbfx fallback).

## Post-upload sample updating (`metadata/`)

Used to correct or annotate samples **after** they are on Flow (see
`reference/ena-arrayexpress-workflow.md` and the `update-sample-metadata` skill).

| Path | Purpose | Upstream |
|------|---------|----------|
| `metadata/flow_public_samples_pull_v3.py` | Shared REST helpers; pull full metadata for all public samples | `flowAPIscripts/pull/flow_public_samples_pull_v3.py` |
| `metadata/pull_project_metadata.py` | Baseline metadata CSV for one project | `flowAPIscripts/pull/pull_project_metadata.py` |
| `metadata/parse_key_resources_antibodies.py` | Key-resources antibody table → purification-agent proposals TSV | `flowAPIscripts/pull/parse_key_resources_antibodies.py` |
| `metadata/apply_metadata_proposals.py` | Confirmed proposals → `samples_updated.csv` + `CONFIRM_METADATA_UPDATES.md` | `flowAPIscripts/pull/apply_metadata_proposals.py` |
| `metadata/flow_public_samples_push_metadata_v2.py` | Diff baseline vs updated → push scalar (GraphQL) + annotation (REST) fields | `flowAPIscripts/pull/flow_public_samples_push_metadata_v2.py` |
| `metadata/flow_edit_samples.py` | **New** — edit `name` / `five_prime_barcode_sequence` / comments etc. by `sample_id` or by accession in the sample name (REST `/edit`) | generalised from the ENA `fix_barcodes_and_submit.py` |

`metadata/*` scripts import each other in-place, so keep them in the same directory.

**Runtime deps:** `flowbio` Python package, `pandas`, `requests`, `pigz` (for removespace).
`flowbio` is only required by scripts that use the GraphQL client
(`uploadsample_flowbio_v6.py`, `flow_public_samples_push_metadata_v2.py`); the
REST-only tools (`flow_edit_samples.py`, `pull_project_metadata.py`,
`flow_public_samples_pull_v3.py`) need just `requests`.

When updating upstream scripts, refresh vendored copies here and re-run flow-compile tests.
