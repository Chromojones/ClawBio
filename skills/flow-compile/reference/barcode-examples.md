# Barcode extraction corpus (agent-assisted → human confirmed)

Examples compiled for `lib/barcode_evidence.py` pattern tuning.

## Where to look (agent)

Order of investigation is conceptual — the agent gathers text; `barcode_evidence.py` runs deterministic regex on whatever corpus you pass in.

1. **GEO series matrix** (`--geo-matrix`) — start here for sample metadata and whether barcodes already appear in `extract_protocol_ch1` or matrix `data_processing`.
2. **Publication Methods — CLIP subsection** — when the matrix says *refer to associated publication*, open the linked paper and read **Methods with focus on the CLIP assay** (iCLIP, eCLIP, PAR-CLIP, etc.). Full Methods often describe multiple barcoding schemes; do not take patterns from RNA-seq, RIP, or other non-CLIP sections. Save the CLIP excerpt as `--paper-text`.
3. **GEO sample Data processing** — fetch or cache per-GSM pages (`--fetch-geo` / `--geo-cache-dir`). The *Data processing* field on the sample page is another strong place to check for trim/barcode sentences. It is not required for every deposit (GSE105082 below used the paper only); hnRNPH (GSM9118554) is the counterexample where GEO *Data processing* carried the barcode trim detail.
4. **Supplementary materials — the final fallback, not a skip.** When Methods and GEO both come up empty, the specification is often in what the paper attaches rather than what it says: supplementary tables (oligo/adapter sequence tables frequently carry the full barcode set per sample), the Key Resources Table, a supplementary methods PDF, the authors' pipeline config or demultiplexing script on GitHub, and GEO/ArrayExpress supplementary *filenames* (GSE105082's per-replicate assignment came from the `_rsem_CGGA.` core in `!Sample_supplementary_file_1`). GSE131210's 6+7 read structure came from primary sources like these, not the paper text. Reach the "no direct evidence" judgement call below only after this pass has genuinely been made, and cite the specific supplementary file in the proposal's evidence the same way a Methods sentence would be quoted.

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

## Judgement calls, decided once

Folded from `DESIGN.md`, which is deleted. These are the cases where evidence is incomplete and
the answer is a judgement rather than a lookup. In all of them the split is the same: **Python
never infers, the agent proposes with its reasoning shown, the researcher confirms.**

### Partial evidence — one sample lacks what its siblings have

Do not block a whole study because one GSM has no direct barcode evidence.

- Resolved GSMs proceed through annotation.
- For the unresolved one the **agent** may propose an N-only pattern matching its siblings'
  length, with the reasoning in `agent_notes`. There is deliberately no automatic inference in
  `barcode_extract.py`: a guess made in Python is indistinguishable from a reading.
- The barcode gate still holds for every GSM, resolved or not.

### The paper lists several barcodes and a filename carries a core

Treat this as replicate-specific assignment, not a contradiction.

GSE105082's methods give `NNNCGGANNN` and `NNNGGCANNN`. The supplementary filenames carry the
cores: GSM2817677 has `_rsem_CGGA.` → `NNNCGGANNN`; GSM2817678 has `_rsem_GGCA.` →
`NNNGGCANNN`. The two samples differ only by that core, so a resolver reading the patterns but
ignoring the per-sample core hands both replicates the same barcode, demultiplexes each into
the other, and produces a study-shaped result with no error.

Present both the paper quote and the filename core, and link core → full pattern. No automatic
CONFLICT flag: the agent compares the sources and writes what it concluded.

### Lengths given, no motif

GSE303135's GEO *Data processing* gives quantities rather than a sequence: "Barcode trimming
(first 15 bp…)" and "min. read length of 30 bp includes 15 bp barcode and UMI regions plus
15 bp sequence insert."

The answer is **15N**, and the reasoning has to be shown rather than the number asserted: GEO
describes the 15 bp as "barcode **and** UMI regions" — two quantities inside a 30 bp total —
and a 30N single 5′ barcode field would be unusually long.

**This is not verifiable from the FASTQ.** Barcode and UMI are both random bases with no
visible boundary, so sampling reads cannot confirm the split. An earlier revision of this rule
said "confirm against the FASTQ", which does not work and would have produced a confident
wrong answer. Flag the guess as resting on general protocol knowledge, and take it to the gate.
