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

After flow-compile produces `annotation.csv`, `headers.txt`, and `pipeline_params.json`:

```bash
python skills/flow-compile/lib/vendor/flow_api/upload/uploadsample_flowbio_v6.py \
  --input annotation.csv \
  --rows 1-2 \
  --project-id 997999200849251656 \
  --base-dir /path/to/fastq_files \
  --dry-run
```

## Pipeline params from headers.txt

See also `reference/eclip-analysis-params.md` for paired-end eCLIP crosslink notes.

| Header pattern | `move_umi_to_header` | `umi_separator` | `encode_eclip` (eCLIP/seCLIP only) |
|----------------|----------------------|-----------------|-------------------------------------|
| Contains `:rbc:` | `false` | `rbc:` | `true` |
| No `:rbc:` (raw SRA) | `true` | `_` | `false` |

Other CLIP methods: `encode_eclip` stays `false` regardless of headers.

`umi_header_format` uses **N-only structure** matching barcode length (e.g. `NNNNNNNNNN` for 10 bp Murat iCLIP, `NNNNNNNNNNNNNNN` for 15 bp iCLIP2). Annotation keeps the literal pattern (`NNNCGGANNN`) for demultiplexing metadata.

## Header cleaning (removespace.py) — superseded

`removespace` now runs inside the clip-seq pipeline on Flow, so nothing renames reads
locally and no `clean_fastq.sh` is generated: `201_fetch` deliberately does no header
cleaning (see `reference/stages.md`). The vendored copy remains for reference only.

## End-to-end scripts (generated in output dir)

| Script | Tool | When |
|--------|------|------|
| `prefetch.sh` | SRA prefetch + fasterq-dump | After `--download` |
| `clean_fastq.sh` | `removespace.py` | Before upload if headers have `/`, spaces, or `_` barcodes |
| `upload.sh` | `uploadsample_flowbio_v6.py` | After FASTQs cleaned; default `--dry-run` |
| `run_analysis.sh` | `flowrunanalysis_flowbio.py` | After upload; passes `--params-json pipeline_params.json` |

The `--case`-driven orchestrator that once ran these end to end is gone; the stages drive
the run now (`flow_compile.py --next`), and `clean_fastq.sh` is no longer generated at all
(header cleaning moved into the clip-seq pipeline — see above).

Credentials: `FLOWBIO_USERNAME` / `FLOWBIO_PASSWORD` (not flow-ai `~/.config/flow/api-token` unless you choose token auth later).

## Organism on Flow

Flow `/organisms` uses short codes (`Hs`, `Mm`). flow-compile enforces these in the annotation sheet before upload.
