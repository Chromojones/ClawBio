# Barcode extraction corpus (agent-assisted → human confirmed)

Examples compiled for `lib/barcode_evidence.py` pattern tuning.

## Where to look (agent)

Order of investigation is conceptual — the agent gathers text; `barcode_evidence.py` runs deterministic regex on whatever corpus you pass in.

1. **GEO series matrix** (`--geo-matrix`) — start here for sample metadata and whether barcodes already appear in `extract_protocol_ch1` or matrix `data_processing`.
2. **Publication Methods — CLIP subsection** — when the matrix says *refer to associated publication*, open the linked paper and read **Methods with focus on the CLIP assay** (iCLIP, eCLIP, PAR-CLIP, etc.). Full Methods often describe multiple barcoding schemes; do not take patterns from RNA-seq, RIP, or other non-CLIP sections. Save the CLIP excerpt as `--paper-text`.
3. **GEO sample Data processing** — fetch or cache per-GSM pages (`--fetch-geo` / `--geo-cache-dir`). The *Data processing* field on the sample page is another strong place to check for trim/barcode sentences. It is not required for every deposit (GSE105082 below used the paper only); hnRNPH (GSM9118554) is the counterexample where GEO *Data processing* carried the barcode trim detail.

## GSM9118554 — hnRNPH iCLIP2 (GSE303135)

**GEO:** [GSM9118554](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSM9118554)

**Data processing (barcode):**
> Barcode trimming (first **15 bp** of read and quality string …)
> min. read length of 30 bp includes **15 bp barcode and UMI regions** plus 15 bp sequence insert

**Extraction:**
| Field | Proposal | Source |
|-------|----------|--------|
| 5' Barcode | `NNNNNNNNNNNNNNN` (**15N**, barcode-only length) | GEO Data processing "first 15 bp" trim sentence |
| UMI | separate 15 bp region per GEO text, not appended to the 5' field | same |
| Protocol | iCLIP2 (PMID 31610236 in extract_protocol) | GEO extract_protocol |

**Agent's job here — evidence + reasoned guess, not just options:** GEO states "15 bp barcode and UMI regions" inside a 30 bp total, which parses as **15 bp barcode + 15 bp UMI as separate regions**, not one 30N run in `5' Barcode Sequence`. The agent should quote the exact Data processing sentence, then propose **15N** as the best guess — reasoning that a combined 30N block is unusually long for a single 5' barcode field (general protocol knowledge, not something derivable from this specific text alone). This guess is **not verifiable from the FASTQ itself**: the barcode and UMI are both random bases, so there is no visible boundary between them in the read to check against. The agent must present the evidence + its reasoning in `CONFIRM_BARCODES.md` and let the user confirm or correct — never silently assume.

**Resolved:** `hnrnph_hs_annotation.tsv` correctly uses **15N** (`NNNNNNNNNNNNNNN`). An earlier note in this doc said "16N" — that was a miscount from an older draft, not a real alternative.

## PMC6307142 — DHX9 iCLIP methods (GSE105082)

**Paper:** [PMC6307142](https://pmc.ncbi.nlm.nih.gov/articles/PMC6307142/) (Murat et al. 2018)

**Methods (demux barcodes):**
> Barcodes (**NNNCGGANNN** and **NNNGGCANNN**) were used for demultiplexing

**Extraction:**
| Field | Proposal | Source |
|-------|----------|--------|
| 5' Barcode | literal `NNNCGGANNN` / `NNNGGCANNN` | iCLIP subsection, Methods (paper) |
| Per-replicate assignment | `CGGA` → `NNNCGGANNN` (GSM2817677); `GGCA` → `NNNGGCANNN` (GSM2817678) | `!Sample_supplementary_file_1` in series matrix (`_rsem_CGGA.` / `_rsem_GGCA.`) |
| Protocol | iCLIP (classic) | paper |

**Agent note:** The 4-mer in the supplementary filename is the **fixed core** of one paper barcode for that replicate — not a competing pattern. Present paper + filename together; user confirms the mapping.

**Note:** GEO sample *Data processing* for this series only says *refer to associated publication* — barcodes came from the paper, not GEO. This is a *methods reference* for the extractor corpus; the hnRNPH upload target is GSE303135 / PMID 41867855.

## Agent + human workflow

1. Agent follows **Where to look** above: matrix → CLIP-focused Methods excerpt (`--paper-text`) → GEO sample *Data processing* when useful → `barcode_proposals.json` (`status: pending_confirmation`)
2. Human reviews `CONFIRM_BARCODES.md` and sets `status: confirmed`
3. Re-run with `--accept-proposals barcode_proposals.json` to build annotation
