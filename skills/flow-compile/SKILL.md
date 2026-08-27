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

Take a published CLIP study from its accession to an analysed project on Flow, with every
field defensible and four points where a person signs off.

**This file is a map, not a rulebook.** Every rule lives in exactly one place, named below.
Earlier revisions restated rules here and drifted: this file once told you to write
`no antibody` for a control while the reference said leave it empty and the validator warned
on the literal string. A reader following this file got it wrong.

## Trigger

Fire when the user wants to:

- upload a published CLIP study (iCLIP, eCLIP, seCLIP, irCLIP, PAR-iCLIP, easyCLIP…) to Flow
- build a Flow annotation sheet from a GEO/ArrayExpress accession
- resolve 5′ barcodes for a CLIP study from its metadata
- import SRA/ENA accessions into a Flow project, or verify an import that already ran
- submit or audit a CLIP-Seq analysis on Flow

Do **not** fire when the user wants to:

- run a non-CLIP assay (RNA-Seq, ChIP-Seq) — those have their own wrappers
- analyse data already on Flow with no upload step — use `flow-bio`
- process FLASH, uvCLAP or PAR-CLIP — detected and refused by name, see
  [`lib/protocol.py`](lib/protocol.py)

## Scope

One task: a CLIP study from accession to analysed Flow project. Barcode resolution, metadata
validation, import and analysis are stages of that one task, not separate skills.

## Workflow

Sixteen numbered stages. Run them in order; each refuses to start before its prerequisites.

```bash
python3 flow_compile.py --status --output <dir>   # what has run, what is waiting
python3 flow_compile.py --next   --output <dir>   # the next command to run
python3 flow_compile.py --run    --output <dir>   # run until something stops
```

```mermaid
flowchart TD
    S00[00 setup] --> S01[01 study] --> S02[02 index] --> S03{{03 barcodes<br/>GATE 1}}
    S03 --> S04[04 annotate] --> S05{{05 metadata<br/>GATE 2}} --> S06{06 route}
    S06 -->|in SRA/ENA| D101[101 preview]
    S06 -->|not in SRA| L201[201 fetch]
    D101 --> P108{{108 params<br/>GATE 3}}
    L201 --> P108
    P108 --> D109[109 sheet] --> D110[110 import] --> V11[11 verify]
    P108 --> L210[210 upload] --> V11
    V11 --> A12{{12 analysis<br/>GATE 4}} --> A13[13 audit]
```

Full table of what each stage decides: **[`reference/stages.md`](reference/stages.md)**.

### Exit codes

| code | meaning | what to do |
|---|---|---|
| `0` | ok | continue |
| `2` | usage | fix the arguments |
| `3` | **gate** | review the named artefact, re-run with the release flag |
| `4` | check failed | the data is wrong; fix it |
| `5` | prerequisite not ok | run the stage it names |

`3` and `4` differ on purpose. A gate is not a failure: the run is paused on a person.

### The four hard stops

None can be skipped. A gated stage does not satisfy a prerequisite, so nothing runs past it.

| gate | stage | released by | rules |
|---|---|---|---|
| 1 | `03_barcodes` | `--accept-proposals` | [`reference/barcode-examples.md`](reference/barcode-examples.md) |
| 2 | `05_metadata` | `--accept-metadata` | [`reference/metadata-accuracy-checklist.md`](reference/metadata-accuracy-checklist.md) |
| 3 | `108_params` | `--accept-params` | [`reference/eclip-analysis-params.md`](reference/eclip-analysis-params.md) |
| 4 | `12_analysis` | `--accept-analysis` | [`reference/eclip-analysis-params.md`](reference/eclip-analysis-params.md) |

Confirming a gate is a decision about evidence, not a flag that silences output. Handing back
an unedited proposals file is not approval: each proposal needs `status: confirmed`.

## Where the rules live

Each fact has one home. If this file and a reference disagree, **the reference is right** —
that is what the last drift cost us.

| topic | file |
|---|---|
| What each stage decides, gates, output-dir contract | [`reference/stages.md`](reference/stages.md) |
| Barcode search order and worked examples | [`reference/barcode-examples.md`](reference/barcode-examples.md) |
| Metadata field rules, controls, antibodies, tags | [`reference/metadata-accuracy-checklist.md`](reference/metadata-accuracy-checklist.md) |
| Annotation column meanings | [`reference/annotation-rules.md`](reference/annotation-rules.md) |
| eCLIP header states and analysis parameters | [`reference/eclip-analysis-params.md`](reference/eclip-analysis-params.md) |
| SRA-direct import, sheet columns, size ceiling | [`reference/sra-direct-import.md`](reference/sra-direct-import.md) |
| ENA / ArrayExpress sourced studies | [`reference/ena-arrayexpress-workflow.md`](reference/ena-arrayexpress-workflow.md) |
| Flow API routes and payload shapes | [`reference/flow-api-notes.md`](reference/flow-api-notes.md) |
| Local patches to vendored upstream code | [`lib/vendor/README.md`](lib/vendor/README.md) |
| **Every incident that produced a guardrail** | [`FAILURES.md`](FAILURES.md) |

## Example output

```
$ python3 flow_compile.py --status --output runs/GSE131210
route: direct (easyCLIP) — accessions resolve in SRA/ENA

  [  ok  ] 00_setup       GSE131210
  [  ok  ] 01_study       public, 13 samples
  [  ok  ] 02_index       13 rows
  [  ok  ] 03_barcodes    13 confirmed
  [  ok  ] 04_annotate    13 rows
  [ wait ] 05_metadata    awaiting approval — re-run with --accept-metadata
  [  --  ] 06_route

next: 05_metadata
```

## Gotchas

Deliberately empty. Every rule that used to live here now lives in `reference/`, and every
incident is indexed in [`FAILURES.md`](FAILURES.md) against the test that encodes it. A rule
stated twice is a rule that will drift, and this section is where the drift started.

## Safety

ClawBio is a research and educational tool. It is not a medical device and does not provide
clinical diagnoses. Consult a healthcare professional before making any medical decisions.

Uploading is outward-facing and hard to reverse. Nothing is submitted without the four gates,
and `110_import` and `210_upload` are dry-run unless given `--submit`.

## Agent boundary

The agent dispatches stages, reads their evidence, and explains the result. The stages execute
and decide. When a gate opens, the agent presents the evidence and **the researcher approves**
— never the agent on the researcher's behalf.

## Chaining partners

- **`flow-bio`** — browse and run pipelines on data already in Flow
- **`nfcore-rnaseq-wrapper`** — RNA-Seq deposits accompanying a CLIP study
- **`pubmed-summariser`** — find candidate CLIP studies to upload

## Maintenance

Review when flowbio changes: the import sheet's reserved columns are read from
`flowbio.cli._accession_sheet.RESERVED_COLUMNS` at test time, so a version bump that moves
them fails CI rather than silently unattaching a study.

Staleness signals: a reference contradicting a stage's behaviour; a `FAILURES.md` anchor with
no test; `lib/vendor/` re-vendored without reapplying [`lib/vendor/README.md`](lib/vendor/README.md).

Deprecate when Flow's own import honours `__annotation` columns and resolves run accessions
without expansion — most of the delivery stages exist to work around those two gaps.
