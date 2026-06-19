# Barcode extraction corpus (agent-assisted → human confirmed)

Examples compiled for `lib/barcode_evidence.py` pattern tuning.

## GSM9118554 — hnRNPH iCLIP2 (GSE303135)

**GEO:** [GSM9118554](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSM9118554)

**Data processing (barcode):**
> Barcode trimming (first **15 bp** of read and quality string …)
> min. read length of 30 bp includes **15 bp barcode and UMI regions** plus 15 bp sequence insert

**Extraction:**
| Field | Proposal | Source |
|-------|----------|--------|
| 5' Barcode (pending) | `NNNNNNNNNNNNNNN` (15N) or combined 30N | GEO trim + min-read sentence |
| UMI | 15N (if split) | same |
| Protocol | iCLIP2 (PMID 31610236 in extract_protocol) | GEO extract_protocol |

**Human check:** Current `hnrnph_hs_annotation.tsv` uses **16N** — confirm against FASTQ structure before upload.

## PMC6307142 — DHX9 iCLIP methods (GSE105082)

**Paper:** [PMC6307142](https://pmc.ncbi.nlm.nih.gov/articles/PMC6307142/) (Murat et al. 2018)

**Methods (demux barcodes):**
> Barcodes (**NNNCGGANNN** and **NNNGGCANNN**) were used for demultiplexing

**Extraction:**
| Field | Proposal | Source |
|-------|----------|--------|
| 5' Barcode | literal `NNNCGGANNN` / `NNNGGCANNN` | iCLIP methods § Data processing |
| Protocol | iCLIP (classic) | paper |

**Note:** This is a *methods reference* for the extractor corpus; the hnRNPH upload target is GSE303135 / PMID 41867855.

## Agent + human workflow

1. Agent gathers GEO sample page + paper methods → `barcode_proposals.json` (`status: pending_confirmation`)
2. Human reviews `CONFIRM_BARCODES.md` and sets `status: confirmed`
3. Re-run with `--accept-proposals barcode_proposals.json` to build annotation
