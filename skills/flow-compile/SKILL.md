---
name: flow-compile
description: >-
  End-to-end CLIP literature-to-Flow pipeline — scan PubMed alerts for new CLIP studies,
  audit GEO/SRA deposits, resolve 5' barcodes from multiple metadata sources, build
  Flow upload annotation sheets, optionally prefetch reads, and upload via Flow API.
license: MIT
metadata:
  version: 0.2.0
  author: Michael Jones <jonesmichaelk1@proton.me>
  domain: clip-seq
  tags:
    - clip
    - iclip
    - flow-bio
    - geo
    - pubmed
    - annotation
    - barcode
  inputs:
    - name: alert_config
      type: file
      format:
        - json
      description: >-
        Optional alert config (PubMed query, date window, known PMIDs to skip).
        Omit with --demo.
      required: false
    - name: geo_matrix
      type: file
      format:
        - txt
        - tsv
      description: GEO series matrix file for the target GSE (or use --gse to fetch).
      required: false
    - name: srr_map
      type: file
      format:
        - tsv
        - csv
      description: GSM-to-SRR mapping table for file download and annotation rows.
      required: false
  outputs:
    - name: report
      type: file
      format: md
      description: Pipeline report with flagged papers, GEO audit, barcode provenance.
    - name: result
      type: file
      format: json
      description: Machine-readable workflow state and per-sample barcode audit.
    - name: annotation
      type: file
      format: csv
      description: Flow-compatible annotation table (upload via uploadsample_flowbio_v6.py).
    - name: flagged_papers
      type: file
      format: json
      description: CLIP-relevant papers from the alert scan.
  dependencies:
    python: '>=3.11'
    packages:
      - pandas>=2.0
      - biopython>=1.80
      - requests>=2.31
      - openpyxl>=3.1
    optional_packages:
      - flowbio>=0.12.0   # Flow.bio client + CLI; `project`/`pubmed` became reserved import columns in 0.12.0
    system:
      - wget      # ENA FASTQ FTP download (ena-arrayexpress-workflow)
      - pigz      # removespace / header clean
  demo_data:
    - path: demo/GSE105082_series_matrix.txt
      description: Full GEO series matrix from NCBI FTP (24 GSMs; demo uses GSM2817677 via srr_map).
    - path: demo_gse105082_srr_map.tsv
      description: GSM2817677 → SRR6181530.
    - path: demo/geo_GSM2817677.txt
      description: Cached GEO sample page for barcode evidence.
    - path: demo/paper_PMC6307142_iclip_excerpt.txt
      description: Methods excerpt with NNNCGGANNN / NNNGGCANNN barcodes.
    - path: demo/SRR6181530.fastq.gz
      description: 5-read FASTQ snippet (matches GSM2817677).
    - path: demo/SRR6181530.cleaned.fastq.gz
      description: removespace output snippet for header-clean tests.
  endpoints:
    cli: python skills/flow-compile/flow_compile.py --output {output_dir} [options]
  openclaw:
    requires:
      bins:
        - python3
    always: false
    emoji: "🧬"
    homepage: https://github.com/Chromojones/ClawBio
    os:
      - darwin
      - linux
    trigger_keywords:
      - flow compile
      - clip pubmed alert
      - new clip paper
      - crosslinking and immunoprecipitation
      - geo clip annotation
      - flow upload clip
      - 5 prime barcode clip
      - build flow annotation sheet
---

# Flow Compile

**Orchestrator skill** — chains specialist stages into a CLIP literature → Flow annotation pipeline.
The agent dispatches and explains; each stage runs deterministic Python.

## Installation

Clone ClawBio and install the Python environment (Python ≥ 3.11):

```bash
git clone https://github.com/ClawBio/ClawBio.git
cd ClawBio
uv sync          # or: pip install -e .
```

`flow_compile.py` and the `lib/` compile stages need only `pandas`, `biopython`,
`requests`, `openpyxl` (all pulled by `uv sync`). The **Flow delivery/metadata
stages** additionally require:

```bash
pip install flowbio          # Flow.bio client (not on PyPI resolution — install directly)
# system tools:
#   wget  — ENA FASTQ FTP download (reference/ena-arrayexpress-workflow.md)
#   pigz  — removespace / FASTQ header clean
```

Set credentials via env (`FLOWBIO_USERNAME` / `FLOWBIO_PASSWORD`) or let the
credentials stage write `.flow_credentials.env` — it also mints a **`FLOW_API_TOKEN`**,
which is what the flowbio CLI (`samples import`, `import-status`) and
the delivery stages
call is vendored under `lib/vendor/flow_api/`, so a ClawBio-only clone is
self-contained (no parent advbfx tree required).

## Preferred workflow — SRA-direct import

**Default to this path.** Flow pulls reads from SRA/ENA itself (`flowbio samples import`,
flowbio ≥ 0.12.0), so there is no local download, no `prefetch`, and no `removespace`
header cleaning. Runbook: **`reference/sra-direct-import.md`**.

```
credentials → geo-matrix → barcode-extract → flow-annotate → metadata gate
  → header preview (ENA byte-range) → import_sheet.csv → samples import → project assign → analysis
```

| Step | Module | Note |
|------|--------|------|
| Header preview | `lib/sra_header_preview.py` | ENA byte-range keeps **original** headers; `fastq-dump` rewrites deflines and is fallback-only |
| Metadata gate | `lib/metadata_validate.py` | `CONFIRM_METADATA.md`; released by `--accept-metadata` |
| Import sheet | `lib/sra_import.py` | Accession must be **SRX/ERX/DRX** — run accessions (`SRR`) fail with HTTP 500 |

`srr_map.tsv` carries both `srr` (header preview) and `srx` (import).

**Use the local-download path instead** when the study is not in SRA/ENA, or when reads must
be transformed before upload (FLASH / uvCLAP UMI extraction).

## Skill chain

```
credentials → pubmed-summariser → geo-matrix → barcode-extract → flow-annotate
  → headers/clean → annotation.xlsx → prefetch → upload → analysis
       ↑                  ↑              ↑                    ↑
  lib/credentials   lib/geo_matrix  lib/barcode_*      lib/flow_annotate
                                                         lib/flow_stages
```

| Stage | Module | Responsibility |
|-------|--------|----------------|
| 0 | `lib/credentials` | Prompt Flow username/password → `.flow_credentials.env` |
| 1 | `pubmed-summariser` | CLIP alert query, flag papers with GSE/SRP |
| 2 | `lib/geo_matrix` | Parse GEO series matrix, GSM column index |
| 3 | `lib/barcode_extract` | Agent-assisted proposals + human confirmation gate |
| 4 | `lib/flow_annotate` | Upload sheet; **Organism always Hs/Mm/Gg** |
| 5 | `lib/fastq_headers` + `lib/header_clean` | `headers.txt`, `clean_fastq.sh` (removespace) |
| 6 | `lib/annotation_xlsx` | `annotation.xlsx` for upload v6 |
| 7 | `prefetch.sh` | SRA download (polled every 4 min with `--run-automated`) |
| 8 | `upload_live.sh` | `uploadsample_flowbio_v6.py` via `annotation.csv` (polled every 4 min) |
| 9 | `run_analysis.sh` | `flowrunanalysis_flowbio.py` + `pipeline_params.json` |

**End-to-end demo:** `DEMO.md` (GSE105082). **Diagram + runbook:** `WORKFLOW.md`.
**ENA / ArrayExpress (SDRF) variant:** `reference/ena-arrayexpress-workflow.md` (worked example E-MTAB-432).

Design decisions from grilling: see `DESIGN.md`.

## Mandatory guardrails (never bypass)

All Flow uploads must go through `flow_compile.py` with these **hard stops**:

### Session inputs (agent collects first)

1. **Credentials** — Flow username/password → `.flow_credentials.env`
2. **Flow project** — user creates project; pass `--flow-project-id`
3. **Accessions** — GSE (+ GSM list) or E-MTAB; `srr_map.tsv` (GSM→SRR or ERS→ERR)
4. **Literature** — primary paper + any referenced CLIP protocol papers the GEO/SDRF cites

### Hard stops (pipeline enforces)

1. **Barcodes (SEVERE)** — `barcode_extract` gathers evidence from matrix + GEO pages + `--paper-text`; writes `CONFIRM_BARCODES.md`. Pipeline **exit 3** until every GSM has `status: confirmed` in `barcode_proposals.json` and you re-run with `--accept-proposals`. If evidence is missing → `NEEDS_USER_INPUT`; **do not invent barcodes**.
2. **FASTQ headers** — when `--fastq-dir` exists, `lib/fastq_headers.py` → `headers.txt`:
   - **`:rbc:` in read name** → `move_umi_to_header=false`, `umi_separator=rbc:`.
   - **eCLIP/seCLIP + `:rbc:`** → `encode_eclip=true`.
   - **eCLIP/seCLIP + no `:rbc:`** → `encode_eclip=false`, `move_umi_to_header=true`, `_` separator.
   - **Other CLIP** → `encode_eclip=false`. See `reference/eclip-analysis-params.md`.
3. **Metadata accuracy (SEVERE)** — `lib/metadata_validate.py` checks the antibody, source, target/tag and 5′ barcode of every row, writes `CONFIRM_METADATA.md` + `metadata_validation.json`, and **blocks on any error** until you re-run with `--accept-metadata`. Full rules and worked traps: `reference/metadata-accuracy-checklist.md`.

   | Field | Rule (one line) |
   |-------|-----------------|
   | `purification_agent` | From the Methods sentence **naming the CLIP assay**, not the first Key Resources row. Format `<Species> Anti-<TARGET> (<Vendor> <Catalog>)`. Vendor **and** catalog required. Controls → `no antibody` |
   | `source` | A specific line (`HEK293T`), never a supplier phrase (`ATCC Cell Lines`) or descriptor (`human embryonic kidney`). `cell line:` beats `source_name_ch1`. HEK293 vs HEK293T must be confirmed against the paper |
   | `source__annotation` | Detail **beyond** the general cell type — lineage/clone (`HeLa` + `Kyoto`). Empty unless the paper names one |
   | `purification_target` | Gene symbol. eCLIP inputs are `SMInput`, **never** the IP's protein |
   | `purification_target__annotation` | Terminal prefix + tag (`c3xFLAG-HBH`, `cV5`, `nGFP`). **Empty for endogenous IPs** |
   | `5' Barcode Sequence` | `ACGTN` literal; execution `umi_header_format` is all-`N` of the same length. eCLIP default `NNNNNNNNNN` |

4. **Analysis** — `CONFIRM_ANALYSIS_PARAMS.md` → `analysis_params.confirmed.json` must match `pipeline_params.json` before `run_analysis.sh`.

**Do not** create ad-hoc `build_*_workflow.py` scripts that skip these gates. See `.cursor/rules/flow-compile-upload-guardrails.mdc`.

Integrates:

- **SRA-direct import** — `reference/sra-direct-import.md` (**canonical workflow**; SRX-only accessions, `project` in the sheet, header preview).
- **Metadata accuracy checklist** — `reference/metadata-accuracy-checklist.md` (per-field search order, formats, never-do list, worked traps).
- **Annotation rules** — `reference/annotation-rules.md` (from Flow annotate / `annotation-file-creation` skill).
- **eCLIP analysis params** — `reference/eclip-analysis-params.md` (`encode_eclip`, PE crosslink on R1).
- **ENA / ArrayExpress workflow** — `reference/ena-arrayexpress-workflow.md` (SDRF barcodes, ENA FTP download, per-UMI-group executions).
- **Flow API concepts** — `reference/flow-api-notes.md` (vocabulary from
  [goodwright flow-ai](https://github.com/goodwright/flow-skills/tree/main/plugins/flow-ai/skills/flow-ai);
  we learn upload/metadata patterns but **do not invoke** the flow-ai plugin).

Bundled Flow API scripts (self-contained clone): upload / analysis / preprocessing
and **post-upload sample updating** live in `lib/vendor/flow_api/` — see that
directory's `README.md` (`metadata/flow_edit_samples.py` for name / 5′ barcode
edits; `metadata/flow_public_samples_push_metadata_v2.py` for bulk metadata push).

## Trigger

**Fire this skill when the user says any of:**
- "flow compile", "compile clip for flow", "build flow annotation from GEO"
- "new CLIP paper", "clip pubmed alert", "crosslinking and immunoprecipitation"
- "resolve 5' barcode for clip upload", "geo matrix to flow sheet"
- "download clip data and upload to flow"

**Do NOT fire when:**
- User only wants a PubMed summary → `pubmed-summariser`
- User only wants variant annotation → `variant-annotation`
- User wants generic Flow API queries without CLIP ingest → external `flow-ai` skill

## Scope

This skill **orchestrates** CLIP literature → GEO/SRA audit → barcode-resolved annotation → optional prefetch/upload. It does not replace `pubmed-summariser` or flow-ai.

## Workflow

**Canonical runbook:** `WORKFLOW.md` (agent playbook + Mermaid diagram + branches).

**Agent hooks:** (1) barcode review with sources (`CONFIRM_BARCODES.md`), (2) Flow project ID, (3) analysis params (`CONFIRM_ANALYSIS_PARAMS.md` → `analysis_params.confirmed.json`). See `DEMO.md`.

### Barcode discovery (agent orchestrates, scripts extract)

| Step | Source | How |
|------|--------|-----|
| 1 | GEO series matrix | `geo_matrix.py` scans cells for `[ACGTN]+` patterns → `barcode_hints` |
| 2 | Per-GSM GEO pages | `geo_sample_fetch.py` / `--geo-cache-dir` / `--fetch-geo` |
| 3 | Paper methods | Agent saves excerpt → `--paper-text` |
| 4 | Referenced papers | Agent fetches when GEO says “refer to publication” |
| 5 | ENA SDRF | `Comment[SUBMITTED_FILE_NAME]` — see `reference/ena-arrayexpress-workflow.md` |
| 6 | Rank + pause | `barcode_evidence.py` → `barcode_extract.py` → **HARD STOP** |

### Pipeline stages

1. **Credentials** + **Flow project ID** (user)
2. **Compile** (`--geo-matrix`, `--srr-map`, `--paper-text`, …) → barcode pause
3. **Confirm barcodes** → `--accept-proposals` → `flow_annotate` + `sample_naming` + `protein_target_annotation`
4. **Download** — `prefetch.sh` (SRA) or ENA `wget` (+ `gzip -t` verify)
5. **Re-compile** `--fastq-dir` → `headers.txt`, `pipeline_params.json`
6. **Branch** — FLASH/uvCLAP `umi_extract.sh` **or** `clean_fastq.sh` (removespace)
7. **Re-compile** again (filenames in `annotation.csv` match disk)
8. **Upload** — `upload_live.sh`
9. **Analysis HARD STOP** — confirm params → `run_analysis.sh`

### End-to-end demo (GSM2817677)

```bash
# Phase A — barcode pause (exit 3)
uv run python skills/flow-compile/flow_compile.py \
  --case gse105082 --output /tmp/flow-compile-demo

# Phase B — after confirming barcodes + Flow project
uv run python skills/flow-compile/flow_compile.py \
  --case gse105082 --output /tmp/flow-compile-demo \
  --accept-proposals /tmp/flow-compile-demo/barcode_proposals.json \
  --fastq-dir skills/flow-compile/demo \
  --flow-project-id 997999200849251656
```

Monitor upload: `tail -f /tmp/flow-compile-demo/logs/upload.log`

## Example Output

```markdown
# Flow Compile Report — GSE105082

| Stage | Status |
|-------|--------|
| GEO matrix | 1 GSM (GSM2817677) |
| SRA files | 1 FASTQ (SRR6181530) |
| Barcodes | 0/1 resolved — paused for confirmation |

## Barcode audit
| GSM | 5' proposal | Source | Status |
|-----|-------------|--------|--------|
| GSM2817677 | NNNCGGANNN | paper:PMC6307142 | pending_confirmation |
```

## Gotchas

- **Flow sample names must not contain spaces.** Sanitize every token before it reaches the name; invalid names break CLIP samplesheets at execution time. Note the source itself now comes from the `cell line:` / `cell type:` characteristic in preference to `!Sample_source_name_ch1` (`lib/flow_annotate.resolve_source`), so a supplier phrase like `ATCC Cell Lines` no longer reaches the name at all — GSE105082 yields `DHX9_Hs_HeLa_Rep1_…`.
- **`samples import` takes SRX, not SRR.** A run accession returns `HTTP 500` with no diagnostic. `lib/sra_import.py` raises before submitting. Keep both in `srr_map.tsv`: `srr` drives the header preview, `srx` drives the import.
- **The import sheet drops `__annotation` columns, but not `project`.** Since flowbio 0.12.0 the reserved columns are `accession`, `name`, `organism`, `project`, `pubmed`, `sample_type`, so set `project` in the sheet. `purification_target__annotation` and `source__annotation` are still forwarded as ordinary metadata keys and discarded by the import job server-side, so annotations still need a post-import `POST /samples/{id}/edit` pass. A colon does not carry one: Flow renders `value:annotation` but stores a colon literally.
- **Never preview headers with `fastq-dump`.** It rewrites deflines to `@SRR…N` even with `--origfmt`, so `:rbc:` becomes undetectable and the whole study takes the wrong params branch. Use the ENA byte-range path; `headers_provenance.md` flags any run that fell back.
- **Replicate labels come from GEO titles**, not guesswork. `iCLIP-DHX9-1` / `iCLIP-DHX9-2` map to `Rep1` / `Rep2`. A title ending in `-2` must not become `Rep1` (GSE105082 bug fixed in `lib/sample_naming.py`).
- **Never guess barcodes.** If protocol text and tags disagree on unrelated patterns, leave `5' Barcode Sequence` empty
  and list the issue in `barcode_audit.json`. When the paper lists multiple barcodes and a supplementary filename
  embeds a short fixed core (e.g. `CGGA` / `GGCA` in `_rsem_*.`), treat it as **replicate variant assignment** — see `DESIGN.md` Q4.
- **GEO matrix column order** must follow `!Sample_geo_accession`; do not assume sample order
  matches SRA sort order.
- **5' vs 3' tags**: FLASH-style studies need the full `5' adapter pattern from methods — see `WORKFLOW.md` FLASH branch (not the bundled demo).
- **Organism must be Hs, Mm, or Gg** — never write `Homo sapiens` to the upload sheet; `lib/organism.py` validates.
- **Upload credentials**: Never print `FLOWBIO_PASSWORD` or API tokens; dry-run by default.
- **Agent boundary**: LLM may read paper PDFs for methods; barcode strings must come from
  skill output fields, not invented in chat.

## Safety

- Research and educational use only. ClawBio is not a medical device.
- Do not download or upload human patient data without appropriate consent and access controls.
- PubMed/GEO/SRA are public APIs; respect NCBI rate limits (≤3 req/s without API key).

## Agent Boundary

The agent routes, reads papers, and explains conflicts. The skill owns accession parsing,
matrix alignment, barcode merging, and annotation CSV generation. The agent must not override
barcode resolution thresholds or skip the audit table.

## Related tooling

Bundled in this skill (`lib/vendor/flow_api/`, self-contained clone):

- Upload: `lib/vendor/flow_api/upload/uploadsample_flowbio_v6.py`
- Analysis: `lib/vendor/flow_api/analysis/flowrunanalysis_flowbio.py`
- Post-upload sample updating: `lib/vendor/flow_api/metadata/` (see its `README.md`)

Outside this repo:

- Annotation skill (Cursor): `advbfx/.cursor/skills/annotation-file-creation/SKILL.md`
- Post-upload metadata skill (Cursor): `advbfx/.cursor/skills/update-sample-metadata/SKILL.md`
- Flow REST skill: [goodwright/flow-skills flow-ai](https://github.com/goodwright/flow-skills/tree/main/plugins/flow-ai/skills/flow-ai)
