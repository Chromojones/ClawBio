# flow-compile — demo (GSE105082 / GSM2817677)

Runs the stages offline against the bundled data: the trunk, both approval gates it can
reach, and a dry-run upload. Every command below is the current stage CLI — this file once
documented a removed monolithic driver, and an agent following it failed on the first
command, so its flags are now checked against the scripts by `tests/unit/test_docs.py`.

| Field | Value |
|-------|-------|
| GSE matrix | `demo/GSE105082_series_matrix.txt` (full, 24 GSMs, from [NCBI FTP](https://ftp.ncbi.nlm.nih.gov/geo/series/GSE105nnn/GSE105082/matrix/)) |
| GSM | **GSM2817677** (`iCLIP-DHX9-1`) — the one sample in `demo_gse105082_srr_map.tsv` |
| SRR | **SRR6181530** — 5-read FASTQ snippet in `demo/` |
| Paper | [PMID 30591072](https://pubmed.ncbi.nlm.nih.gov/30591072/), excerpt in `demo/paper_PMC6307142_iclip_excerpt.txt` |
| Barcode (from methods) | `NNNCGGANNN` |

Run everything from `skills/flow-compile/` with `OUT=/tmp/flow-compile-demo` (any empty
directory). `python3 flow_compile.py --status --output $OUT` shows where you are at any point;
`--next` prints the next command with its required flags as placeholders.

## The trunk

```bash
python3 stages/00_setup.py --output $OUT --accession GSE105082 --offline
python3 stages/01_study.py --output $OUT
python3 stages/02_index.py --output $OUT \
  --geo-matrix demo/GSE105082_series_matrix.txt --srr-map demo_gse105082_srr_map.tsv
```

`--offline` records that no Flow credentials exist, so nothing later tries the network. A
real run drops it and sets `FLOWBIO_USERNAME` / `FLOWBIO_PASSWORD` — or a token as
`FLOW_TOKEN` / `FLOW_API_TOKEN`, both honoured. The sibling `flow-bio` skill's
`FLOW_USERNAME` / `FLOW_PASSWORD` are **not** read (00_setup says so out loud if it sees
them). Add `--project-id <flow project>`. 02 warns that the srr_map carries no `srx` column: correct,
and why this demo takes the local line at the branch.

## Gate 1 — barcodes (exit 3, on purpose)

```bash
python3 stages/03_barcodes.py --output $OUT \
  --geo-matrix demo/GSE105082_series_matrix.txt \
  --geo-cache-dir demo \
  --paper-text demo/paper_PMC6307142_iclip_excerpt.txt
```

The stage stops with exit `3` — a gate, not a failure — and writes
`$OUT/barcode_proposals.json`. The expected proposal for GSM2817677 is **`NNNCGGANNN`**,
with its evidence quoted from the paper excerpt and the GEO record. Review it, set
`"status": "confirmed"` on that proposal (an unedited file is not approval), then supply
the file — supplying it IS the release:

```bash
python3 stages/03_barcodes.py --output $OUT --accept-proposals $OUT/barcode_proposals.json
```

## Annotation and gate 2 — metadata

```bash
python3 stages/04_annotate.py --output $OUT \
  --geo-matrix demo/GSE105082_series_matrix.txt --srr-map demo_gse105082_srr_map.tsv \
  --paper-text demo/paper_PMC6307142_iclip_excerpt.txt
python3 stages/05_metadata.py --output $OUT
```

04 builds `annotation.raw.csv` (one row: `DHX9_Hs_HeLa_Rep1_SRR6181530`). 05 stops at exit
`3` with one real error — the paper excerpt never names the purification antibody, so
`Purification Agent` is empty. That is the gate doing its job. Review
`$OUT/metadata_report.md` against
[`reference/metadata-accuracy-checklist.md`](reference/metadata-accuracy-checklist.md),
then:

```bash
python3 stages/05_metadata.py --output $OUT --accept-metadata
```

## The branch, and gate 3 — parameters

```bash
python3 stages/06_route.py --output $OUT --force-local --reason "offline demo, srr_map has no SRX"
zcat demo/SRR6181530.fastq.gz | awk 'NR%4==1' \
  | python3 -c 'import json,sys; print(json.dumps([l.strip() for l in sys.stdin]))' \
  > $OUT/headers.json
python3 stages/201_fetch.py --output $OUT --headers $OUT/headers.json --fastq-dir demo
python3 stages/108_params.py --output $OUT
```

A real SRA-hosted study omits `--force-local` (06 routes direct, and 101_preview samples
headers straight from ENA instead of the `zcat`). 108 classifies the bundled headers as
`raw`, derives `umi_header_format: NNNNNNNNNN` from the confirmed 10-nt barcode, and stops
at exit `3`. Confirm against [`reference/eclip-analysis-params.md`](reference/eclip-analysis-params.md)
— the UMI length must come from the authors' pipeline config, not composition — then:

```bash
python3 stages/108_params.py --output $OUT --accept-params
```

## Dry-run delivery

```bash
python3 stages/210_upload.py --output $OUT
```

Prepares `upload_sheet.csv` for the one sample and stops there: nothing is submitted
without `--submit`, and nothing should be for the demo. The remaining stages need a live
Flow project — `11_verify --live-samples`, `12_analysis`, `13_audit --processes` — and
`flow_compile.py --next` will print each with its required flags when you get there.

## What a real run does differently

- `00_setup` without `--offline`, with credentials and `--project-id`
- `01_study` with `--sizes` (ENA filereport) and `--search-results` (Flow `/search`) — see
  [`reference/sra-direct-import.md`](reference/sra-direct-import.md) for both recipes
- an `srr_map.tsv` with the `srx` column populated, so 06 routes **direct** and delivery is
  `109_sheet` → `110_import` instead of `210_upload`
