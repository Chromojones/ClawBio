# flow-compile — demo (GSE105082 / GSM2817677)

Canonical bundled demo: **one sample** matching the FASTQ snippets in `demo/`.

| Field | Value |
|-------|-------|
| GSE matrix | `demo/GSE105082_series_matrix.txt` (full, from [NCBI FTP](https://ftp.ncbi.nlm.nih.gov/geo/series/GSE105nnn/GSE105082/matrix/)) |
| GSM | **GSM2817677** (`iCLIP-DHX9-1`) |
| SRR | **SRR6181530** |
| Paper | [PMID 30591072](https://pubmed.ncbi.nlm.nih.gov/30591072/) |
| Barcode (from methods) | `NNNCGGANNN` |
| Bundled FASTQ | `demo/SRR6181530.fastq.gz` (5 reads) + `demo/SRR6181530.cleaned.fastq.gz` |
| Flow project (example) | https://app.flow.bio/projects/997999200849251656/ |

## What the agent should do first

1. Ask for **Flow credentials** and a **Flow project ID** (user creates project in UI).
2. Confirm target: GSE105082, GSM2817677 (or use `--case gse105082` preset).
3. Run Phase A below — pipeline **must pause** at barcode confirmation.

## Phase A — Barcode extraction (mandatory pause, exit 3)

```bash
cd ClawBio

uv run python skills/flow-compile/flow_compile.py \
  --case gse105082 \
  --output /tmp/flow-compile-demo
```

Review:

- `/tmp/flow-compile-demo/CONFIRM_BARCODES.md`
- `/tmp/flow-compile-demo/barcode_proposals.json`

Expected proposal for GSM2817677: **`NNNCGGANNN`** from `demo/paper_PMC6307142_iclip_excerpt.txt`
(“Barcodes (NNNCGGANNN and NNNGGCANNN) were used for demultiplexing”).

Set `status: confirmed` in `barcode_proposals.json` before Phase B.

## Phase B — Headers + params (bundled FASTQ, no SRA download)

Uses the 5-read snippet only — enough to test `headers.txt`, `pipeline_params.json`, and `clean_fastq.sh`:

```bash
uv run python skills/flow-compile/flow_compile.py \
  --case gse105082 \
  --output /tmp/flow-compile-demo \
  --accept-proposals /tmp/flow-compile-demo/barcode_proposals.json \
  --fastq-dir skills/flow-compile/demo \
  --flow-project-id 997999200849251656
```

Before analysis (if you run upload/analysis):

```bash
cp /tmp/flow-compile-demo/pipeline_params.json \
   /tmp/flow-compile-demo/analysis_params.confirmed.json
```

## Phase C — Full automated workflow (real SRA download)

```bash
mkdir -p ~/gse105082/fastq_files

uv run python skills/flow-compile/flow_compile.py \
  --case gse105082 \
  --output /tmp/flow-compile-demo \
  --accept-proposals /tmp/flow-compile-demo/barcode_proposals.json \
  --fastq-dir ~/gse105082/fastq_files \
  --flow-project-id 997999200849251656 \
  --run-automated
```

Monitor: `tail -f /tmp/flow-compile-demo/logs/upload.log`

## Agent checklist

- [ ] Flow project ID obtained from user
- [ ] Credentials in `.flow_credentials.env` (never commit)
- [ ] Barcode evidence presented with source quotes — **not invented**
- [ ] User confirmed `barcode_proposals.json`
- [ ] After download: `headers.txt` reviewed
- [ ] `analysis_params.confirmed.json` matches `pipeline_params.json` before analysis

See **`WORKFLOW.md`** for the full branching diagram (FLASH, uvCLAP, ENA).
