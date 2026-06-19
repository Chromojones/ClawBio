---
name: flow-compile
description: >-
  End-to-end CLIP literature-to-Flow pipeline — scan PubMed alerts for new CLIP studies,
  audit GEO/SRA deposits, resolve 5' barcodes from multiple metadata sources, build
  Flow upload annotation sheets, optionally prefetch reads, and upload via Flow API.
license: MIT
metadata:
  version: 0.1.0
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
  demo_data:
    - path: demo_geo_matrix.txt
      description: Two-sample excerpt from GSE118265 (FLASH/iCLIP) with barcode protocol text.
    - path: demo_srr_map.tsv
      description: GSM3323898–GSM3323899 mapped to SRR7657599–SRR7657600 (2 runs, paired-end).
    - path: demo_alert.json
      description: Synthetic PubMed alert payload for PMID 31802123.
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
| 8 | `upload_live.sh` | `uploadsample_flowbio_v6.py` (polled every 4 min) |
| 9 | `run_analysis.sh` | `flowrunanalysis_flowbio.py` + `pipeline_params.json` |

**End-to-end demo:** `DEMO.md` (GSE105082). **Diagram:** `WORKFLOW.md`.

Design decisions from grilling: see `DESIGN.md`.

Integrates:

- **Annotation rules** — `reference/annotation-rules.md` (from Flow annotate / `annotation-file-creation` skill).
- **Flow API concepts** — `reference/flow-api-notes.md` (vocabulary from
  [goodwright flow-ai](https://github.com/goodwright/flow-skills/tree/main/plugins/flow-ai/skills/flow-ai);
  we learn upload/metadata patterns but **do not invoke** the flow-ai plugin).

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

**Manual gates only:** (1) confirm barcodes, (2) create Flow project. See `DEMO.md`.

1. **Credentials** (`--run-automated` / `--execute-upload`): prompt → `.flow_credentials.env`
2. **PubMed alert** (`--scan-pubmed`): flagged papers; demo uses cache unless `--scan-pubmed`
3. **GEO audit**: Parse series matrix; index GSM columns
4. **Barcode extraction**: Agent + GEO/paper text → `barcode_proposals.json`; **pause** until confirmed
5. **Annotation build**: CSV + XLSX; Organism ∈ `{Hs, Mm, Gg}`
6. **Header inspection**: `headers.txt` + `pipeline_params.json` (move_umi, umi_header_format)
7. **Header clean**: `clean_fastq.sh` → removespace when headers have `/`, spaces, or `_`
8. **Prefetch** (`--download` / `--run-automated`): `prefetch.sh`; poll every 4 min
9. **Upload**: `upload_live.sh`; monitor with `tail -f logs/upload.log`
10. **Analysis**: `run_analysis.sh` with `--params-json pipeline_params.json`

### End-to-end demo (GSE105082)

```bash
# Phase A — barcode pause
uv run python skills/flow-compile/flow_compile.py \
  --case gse105082 --output /tmp/gse105082-demo

# Phase B — after confirming barcodes + Flow project
uv run python skills/flow-compile/flow_compile.py \
  --case gse105082 --output /tmp/gse105082-demo \
  --accept-proposals /tmp/gse105082-demo/barcode_proposals.json \
  --fastq-dir ~/gse105082/fastq_files \
  --run-automated
```

Monitor upload: `tail -f /tmp/gse105082-demo/logs/upload.log`

## Example Output

```markdown
# Flow Compile Report — GSE118265

| Stage | Status |
|-------|--------|
| PubMed alert | 1 CLIP paper flagged (PMID 31802123) |
| GEO matrix | 2 GSM columns parsed |
| SRA files | 4 FASTQ paths (2 runs × PE) |
| Barcodes | 2/2 resolved (protocol + 3' tag) |

## Barcode audit
| GSM | 5' Barcode | Confidence | Sources |
|-----|------------|------------|---------|
| GSM3323898 | NNBBNGTGGAANN | high | extract_protocol, 3' tag GTGGAA |
```

## Gotchas

- **Never guess barcodes.** If protocol text and tags disagree, leave `5' Barcode Sequence` empty
  and list the conflict in `barcode_audit.json`.
- **GEO matrix column order** must follow `!Sample_geo_accession`; do not assume sample order
  matches SRA sort order.
- **5' vs 3' tags**: FLASH-style studies encode condition in `3' tag` but Flow needs the full
  `5' adapter pattern (`NNBBN{tag}NN`) from methods text — see GSE118265 demo.
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

## Related tooling (outside this repo)

- Upload: `flowAPIscripts/upload/uploadsample_flowbio_v6.py`
- Annotation skill (Cursor): `advbfx/.cursor/skills/annotation-file-creation/SKILL.md`
- Flow REST skill: [goodwright/flow-skills flow-ai](https://github.com/goodwright/flow-skills/tree/main/plugins/flow-ai/skills/flow-ai)
