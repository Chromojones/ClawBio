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
| flowbio CLI + curl for upload | `flowAPIscripts/upload/uploadsample_flowbio_v6.py` (`flowbio.v2.Client`) |
| `GET /annotation/<sample_type>` template | advbfx `Testtemplate.xlsx` + annotation-file-creation rules |
| Agent-driven API discovery | Pre-mapped column → metadata keys in upload script |

## Upload path

Flow project for GSE105082 (DHX9 iCLIP): **997999200849251656**  
https://app.flow.bio/projects/997999200849251656/

Project creation is manual for now; a future stage should call `POST /projects` (see flow-ai notes).

After flow-compile produces `annotation.csv`, `annotation.xlsx`, `headers.txt`, and `pipeline_params.json`:

```bash
python flowAPIscripts/upload/uploadsample_flowbio_v6.py \
  --input annotation.csv \
  --rows 1-2 \
  --project-id 997999200849251656 \
  --base-dir /path/to/fastq_files \
  --dry-run
```

## Pipeline params from headers.txt

| Header pattern | `move_umi_to_header` | `umi_separator` |
|----------------|----------------------|-----------------|
| Contains `:rbc:` | `false` | `rbc:` |
| Underscore barcode or barcode in read | `true` | `_` |

`umi_header_format` uses **N-only structure** matching barcode length (e.g. `NNNNNNNNNN` for 10 bp Murat iCLIP, `NNNNNNNNNNNNNNN` for 15 bp iCLIP2). Annotation keeps the literal pattern (`NNNCGGANNN`) for demultiplexing metadata.

## Header cleaning (removespace.py)

When sampled headers contain `/`, spaces, or `_` barcode suffixes, flow-compile writes `clean_fastq.sh` calling `flowAPIscripts/preprocessing/removespace.py` (spaces/slashes → underscore). Upload **`.cleaned.fastq.gz`** files — see `fastq_upload_manifest.tsv`.

## End-to-end scripts (generated in output dir)

| Script | Tool | When |
|--------|------|------|
| `prefetch.sh` | SRA prefetch + fasterq-dump | After `--download` |
| `clean_fastq.sh` | `removespace.py` | Before upload if headers have `/`, spaces, or `_` barcodes |
| `upload.sh` | `uploadsample_flowbio_v6.py` | After FASTQs cleaned; default `--dry-run` |
| `run_analysis.sh` | `flowrunanalysis_flowbio.py` | After upload; passes `--params-json pipeline_params.json` |

```bash
# Full local run (after barcode confirmation)
bash prefetch.sh
bash clean_fastq.sh
bash upload.sh                    # dry-run
bash upload.sh  # edit: remove --dry-run, or use --execute-upload
bash run_analysis.sh              # interactive login + submit
```

Or orchestrate with:

```bash
uv run python skills/flow-compile/flow_compile.py --case gse105082 ... \
  --execute-upload --execute-analysis
```

Credentials: `FLOWBIO_USERNAME` / `FLOWBIO_PASSWORD` (not flow-ai `~/.config/flow/api-token` unless you choose token auth later).

## Organism on Flow

Flow `/organisms` uses short codes (`Hs`, `Mm`). flow-compile enforces these in the annotation sheet before upload.
