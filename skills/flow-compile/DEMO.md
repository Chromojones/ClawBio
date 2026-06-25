# flow-compile — end-to-end demo (GSE105082)

Canonical demo dataset: **GSE105082** DHX9 iCLIP ([PMID 30591072](https://pubmed.ncbi.nlm.nih.gov/30591072/)).  
Flow project: https://app.flow.bio/projects/997999200849251656/

Bundled demo FASTQ snippet: `demo/SRR6181530.fastq.gz` (5 reads — for header/clean tests only).  
Full runs: prefetch SRR6181530 + SRR6181534 (~900 MB each).

## Manual gates

1. **Confirm barcodes** — edit `barcode_proposals.json` → `status: confirmed`
2. **Create Flow project** — pass `--flow-project-id` (preset `997999200849251656` for `--case gse105082`)
3. **Confirm analysis params** — review `pipeline_params.json`, then create
   `analysis_params.confirmed.json` (copy must match current params)

---

## Phase A — Barcode extraction (pauses)

```bash
cd projects/clawbio/ClawBio

uv run python skills/flow-compile/flow_compile.py \
  --case gse105082 \
  --output /tmp/gse105082-demo
```

Exit code **3** = paused. Review:

- `/tmp/gse105082-demo/CONFIRM_BARCODES.md`
- `/tmp/gse105082-demo/barcode_proposals.json`

Confirm barcodes (rep1: `NNNCGGANNN`, rep2: `NNNGGCANNN`), set each proposal `status: confirmed`.

---

## Phase B — Full automated workflow

```bash
mkdir -p ~/gse105082/fastq_files

uv run python skills/flow-compile/flow_compile.py \
  --case gse105082 \
  --output /tmp/gse105082-demo \
  --accept-proposals /tmp/gse105082-demo/barcode_proposals.json \
  --fastq-dir ~/gse105082/fastq_files \
  --run-automated
```

**Step 0 — credentials:** prompts for Flow username/password → writes `.flow_credentials.env` (mode 600).

**Then automatically (4-min polling between long steps):**

| Step | Script | Log file |
|------|--------|----------|
| Compile | (Python) | stdout |
| Download | `prefetch.sh` | `logs/prefetch.log` |
| Header clean | `clean_fastq.sh` | `logs/clean.log` |
| Re-compile | (Python) | stdout |
| Upload | `upload_live.sh` | `logs/upload.log` |
| Analysis | `run_analysis.sh` | `logs/analysis.log` |

Before `run_analysis.sh` executes, it enforces a manual params check:

```bash
cp /tmp/gse105082-demo/pipeline_params.json \
   /tmp/gse105082-demo/analysis_params.confirmed.json
```

---

## Monitor upload progress

### During `--run-automated`

The orchestrator prints status **every 4 minutes** on stdout:

```
… Flow upload still running (12.0 min, check again in 4 min)
  log: /tmp/gse105082-demo/logs/upload.log
  latest: Row 1: DHX9_Hs_ATCC Cell Lines_Rep1_SRR6181530
```

### Live log (recommended — open a second terminal)

```bash
tail -f /tmp/gse105082-demo/logs/upload.log
```

You will see per-row progress from `uploadsample_flowbio_v6.py`:

```
Row 1: DHX9_Hs_ATCC Cell Lines_Rep1_SRR6181530
  sample_type=CLIP
  data={reads1: .../SRR6181530.cleaned.fastq.gz}
  -> uploaded sample id=603430893796592425
...
Completed. successful=2, failed=0, total=2
```

### Check if upload is still running

```bash
ps aux | grep uploadsample_flowbio
ls -lh /tmp/gse105082-demo/logs/upload.log   # file grows while uploading
```

### After upload

```bash
grep -E 'successful|failed|uploaded sample' /tmp/gse105082-demo/logs/upload.log
```

Success = `successful=2, failed=0`.

---

## Visible terminal (optional)

For a scrolling master log with `tee`:

```bash
bash /tmp/gse105082-demo/run_workflow.sh
# separate window:
tail -f /tmp/gse105082-demo/logs/workflow.log
```

---

## Quick test without SRA download

Uses bundled 5-read FASTQ snippet only (upload dry-run / header inspection):

```bash
uv run python skills/flow-compile/flow_compile.py \
  --case gse105082 \
  --output /tmp/gse105082-quick \
  --accept-proposals /tmp/gse105082-demo/barcode_proposals.json \
  --fastq-dir skills/flow-compile/demo
```

---

## Legacy demos

| Case | GSE | Purpose |
|------|-----|---------|
| `--demo` | GSE118265 | FLASH barcode profile (no pause) |
| `--case hnrnph` | GSE303135 | iCLIP2 barcode pause demo |

See `WORKFLOW.md` for the Mermaid diagram.
