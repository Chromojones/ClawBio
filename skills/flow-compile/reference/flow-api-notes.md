# Flow API notes (condensed)

Adapted from [goodwright/flow-skills flow-ai](https://github.com/goodwright/flow-skills/tree/main/plugins/flow-ai/skills/flow-ai).
**We learn from this skill; we do not depend on it at runtime.**

## What we borrow

- Resource hierarchy: project → sample → fileset → data
- Upload semantics: demultiplexed sample upload, metadata bag keys
- Token discipline: never log credentials

## What we use instead

| flow-ai approach | flow-compile approach |
|------------------|----------------------|
| flowbio CLI + curl for upload | `lib/vendor/flow_api/upload/uploadsample_flowbio_v6.py` (`flowbio.v2.Client`) |
| `GET /annotation/<sample_type>` template | advbfx `Testtemplate.xlsx` + annotation-file-creation rules |
| Agent-driven API discovery | Pre-mapped column → metadata keys in upload script |

## Upload path

Flow project for GSE105082 (DHX9 iCLIP): **997999200849251656**  
https://app.flow.bio/projects/997999200849251656/

### Listings paginate, and the envelope lies about it

`GET /projects/{id}/samples` returns `{"count": <project total>, "page": n, "samples": [...]}`.
`count` is the **total in the project**, not the page size — and the page size defaults to
**10**, capping at 100 (>100 is HTTP 400). So a bare listing of a 24-sample project returns 10
samples beside an envelope saying 24, and looks complete.

Collect every page through `FlowClient.paginate` / `project_samples`, which refuse to return a
short collection. `names_from_listing` and `find_import_discrepancies` also refuse an envelope
holding fewer samples than it promises, because the two failure modes are opposite and both
bad: a truncated pre-flight reports "clean import" and duplicates the study, while a truncated
verification reports every unfetched sample as missing.

### Deleting a sample

```python
FlowClient(token).delete_sample(sample_id)   # POST /samples/{id}/delete, then GET must 404
```

Never `DELETE /samples/{id}`. It returns `200` with the full sample body whether or not it
deleted anything — it has done both — so a sample can survive three "successful" deletes.
`POST /samples/{id}/delete` answers `{"success": true}`, and that is still not the evidence:
`delete_sample` re-fetches and accepts only a **404**. A sample that re-reads, or a re-read
that errors any other way, raises.

Deleting a *read mate* from a sample is a different operation and breaks the sample; see
`reference/sra-direct-import.md` §5b.

### Project creation

`POST /projects/new` with `{"name": …, "description": …}` returns the created project as
`{"id": …, …}`. The route was read from the app bundle's own create-project call — the
flow-ai notes document only the read endpoints, and flowbio has no project mutation. Because
several Flow write endpoints return `200` while doing nothing, `FlowClient.create_project`
(`lib/flow_client.py`) re-reads `GET /projects/{id}` and refuses a creation whose name does
not match. Use it through the stage:

```bash
python3 stages/00_setup.py --output <dir> --accession GSE… --create-project "GSE… CLIP"
```

The created id is recorded as the run's `project_id`, exactly as `--project-id` would adopt
an existing one.

On the local line, `210_upload` writes `upload_sheet.csv` and prints the exact upload command
— `--dry-run` first — with `--rows`, `--project-id` and an absolute `--base-dir` filled in.

## Pipeline params from the header preview

See also `reference/eclip-analysis-params.md` for paired-end eCLIP crosslink notes.

The parameters come from the **four header states** in `reference/eclip-analysis-params.md`
§3, derived by `lib/header_state.py` — two booleans (`:rbc:` present or not) cannot express
them. `encode_eclip` is true for exactly one: a randomer prepended to the title, where
`encode_moveumi` takes the first colon field as the UMI. On an already-extracted `:rbc:`
header it would take the instrument name instead and collapse the library.

`umi_header_format` uses **N-only structure** matching barcode length (e.g. `NNNNNNNNNN` for 10 bp Murat iCLIP, `NNNNNNNNNNNNNNN` for 15 bp iCLIP2). Annotation keeps the literal pattern (`NNNCGGANNN`) for demultiplexing metadata.

## Header cleaning

`removespace` runs inside the clip-seq pipeline on Flow, so nothing renames reads locally and
`201_fetch` does no header cleaning. The vendored copy is reference only.

## Commands the stages hand you

Outward-facing steps are run by the agent, from the command the stage prints.

| Stage | Writes | Prints for you to run |
|---|---|---|
| `110_import` | `import_job.json` (with `--submit`) | the `flowbio samples import-status` poll |
| `210_upload` | `upload_sheet.csv` | the vendored upload command, `--dry-run` first |
| `11_verify` | `verify_report.json`, `repair_edits.csv` | `flow_edit_samples.py --edits … --dry-run`, then `--yes` |
| `12_analysis` | `run_analysis.sh` | `bash run_analysis.sh` |

Credentials: `FLOWBIO_USERNAME` / `FLOWBIO_PASSWORD`, or a token — `FLOW_API_TOKEN`, `FLOW_TOKEN`,
or `~/.config/flow/api-token`, checked in that order by `flow_client.resolve_token`.

## Organism on Flow

Flow `/organisms` uses short codes (`Hs`, `Mm`). flow-compile enforces these in the annotation sheet before upload.
