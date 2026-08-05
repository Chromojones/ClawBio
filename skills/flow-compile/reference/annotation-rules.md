# Annotation rules (condensed)

Source of truth for field mapping: `advbfx/.cursor/skills/annotation-file-creation/SKILL.md`.

## Upload targets

- `flowAPIscripts/upload/uploadsample_flowbio_v6.py`
- Template columns: `flowAPIscripts/test-datasets/Testtemplate.xlsx`

## Required columns (CLIP)

| Column | Rule |
|--------|------|
| File / File name | FASTQ path relative to `--base-dir` |
| File 2 | Mate pair for PE |
| Sample Name | `protein_org_cell_RepN_SRR` — **no spaces**; underscores only; derive `RepN` from GEO `!Sample_title` suffix (`iCLIP-DHX9-2` → `Rep2`), not from SRA run index alone |
| Type | `CLIP` |
| Experimental Method | `iCLIP`, `eCLIP`, `PAR-CLIP`, etc. |
| 5' Barcode Sequence | From barcode resolver; **Flow metadata allows only `A`, `C`, `G`, `T`, `N`**. FLASH/IUPAC grammar (`R`, `Y`, `B`) is normalized to `N` before upload (`normalize_flow_barcode` in `lib/barcode_evidence.py`). Replicate identity (RR vs YY) is carried in sample name / GEO title, not in R/Y letters. |
| GEO ID | `GSM…` per row |
| Scientist | **First author** full name from linked PubMed record (`paper_metadata_enrich`); never GEO contact name |
| PI | **Last author** full name from linked PubMed record (`paper_metadata_enrich`); never GEO contact name |
| PubMed ID | Series `!Series_pubmed_id` (verify against publication — ArrayExpress deposits may be wrong) |
| Protein (Purification Target) | Gene symbol from title/characteristics |
| Organism | `Hs`, `Mm`, `Gg` only — never full scientific names |
| Purification Target Annotation | Tag on protein (`c3xFLAG-HBH`); API key `purification_target__annotation`; displays as `GENE:annotation` |
| Purification Agent | Full antibody string from **paper Methods** when GEO/SDRF is vague; format `Mouse Anti-TARGET (Vendor Catalog)` — resolved by mandatory `paper_metadata_enrich` stage when a PubMed ID is present; warnings in `ANNOTATION_WARNINGS.md` |

## eCLIP / seCLIP — upload the crosslink mate

Paired-end eCLIP FASTQs have two mates and Flow upload is single-end, but the mate to keep
is **read 2, not read 1**. In PE eCLIP read 1 holds only the 7 nt inline demultiplexing
barcode, while **read 2 carries the randomer (N5/N10) followed by the crosslink** — the Yeo
pipeline extracts it with `samtools view -f 128`, and `eclipdemux` trims the randomer from
"the front of 2nd read in pair". `apply_eclip_crosslink_mate_filenames` promotes File 2 →
File for eCLIP rows.

**seCLIP** is genuinely single-end: read 1 is the only read and carries the crosslink.

For raw SRA reads without `:rbc:`, Flow extracts the UMI from the uploaded read
(`move_umi_to_header=true`, `umi_header_format=NNNNNNNNNN`, `encode_eclip=false`).
Full read-structure table, header states and literature: `reference/eclip-analysis-params.md`.

## FLASH UMI extract (pre-upload)

FLASH PE libraries carry **13 nt** on read 2 (`NNXXXXXXNNNNN`: 2 random + 6 UMI + 5 flank) per [PMC7026646](https://pmc.ncbi.nlm.nih.gov/articles/PMC7026646/) and `projects/flash/umi-extract.sh`. flow-compile writes `umi_extract.sh` (umi_tools) to move UMI into read 1 headers, then uploads **read 1 only** (`*_1.umi.fastq.gz`). Do **not** run `removespace.py` on FLASH UMI outputs — headers like `@SRR….1_CCGCCCT 1 length=74` are correct; samtools drops text after the space before `umi_dedup`. Analysis uses `move_umi_to_header=false`, `umi_separator=_`.

## GSM ↔ SRR alignment

1. Index matrix columns by `!Sample_geo_accession`.
2. Map SRR via SRA run pages or curated `srr_map.tsv`.
3. Prefer GEO `Title` over weak SRA `LibraryName`.
4. **Replicate number** comes from GEO title patterns: trailing `-1`/`-2`, or explicit `rep1`/`rep2`. Do not default both replicates to `Rep1`.
5. **Sanitize tokens**: replace spaces with `_`; strip characters outside `[A-Za-z0-9_]`. Flow samplesheets reject spaces in sample names.

## Agent hooks (pause points)

| Hook | Artifact | Agent action |
|------|----------|--------------|
| Barcode | `CONFIRM_BARCODES.md`, `barcode_proposals.json` | Present 5' barcode, **source** (`evidence[].source`), and quote; wait for `status: confirmed` |
| Analysis params | `CONFIRM_ANALYSIS_PARAMS.md`, `pipeline_params.json` | Present derived `move_umi_to_header`, `umi_header_format`, etc.; user copies to `analysis_params.confirmed.json` |
| Paper metadata | `ANNOTATION_WARNINGS.md`, `annotation_warnings.json` | After annotation build: Scientist = first author; PI = last author; purification agents from paper Methods/PMC; review warnings for empty/generic fields |
| Flow project | CLI `--flow-project-id` | User creates project in Flow UI |

## Barcode source priority

1. Curated override (alert config)
2. `!Sample_extract_protocol_ch1` / `!Sample_data_processing` (adapter grammar)
3. `!Sample_description`
4. `!Sample_characteristics_ch1` (`3' tag`, `5' tag`)
5. Paper methods text (manual `--paper-text`)

## Agent barcode search (conceptual)

Investigation is agent-driven; scripts only regex-scan text you attach (`--paper-text`, `--geo-cache-dir`, `--fetch-geo`).

1. **GEO series matrix first** (`--geo-matrix`) — titles, `extract_protocol_ch1`, matrix `data_processing` if present, series PMID.
2. **Publication Methods — CLIP subsection** — when GEO defers to the paper, read Methods and **focus on the CLIP assay section** (iCLIP, eCLIP, PAR-CLIP, etc.). The same paper often describes several barcoding formats (RNA-seq, RIP, facility indexes, other protocols); pass only the CLIP-relevant excerpt to `--paper-text`.
3. **GEO sample Data processing** — per-GSM pages via `--fetch-geo` or cached `geo_GSM*.txt`. The *Data processing* block is a good secondary check for trim length and barcode prose (see `reference/barcode-examples.md`, hnRNPH). It is not always populated — e.g. GSE105082 iCLIP samples point back to the paper.

See `reference/barcode-examples.md` for worked examples and the human confirmation gate.

## Flow API metadata keys

`uploadsample_flowbio_v6.py` maps `5' Barcode Sequence` → `five_prime_barcode_sequence`,
`Protein (Purification Target)` → `purification_target`. Flow sample JSON may expose
`protein_target__annotation` (double underscore) for enriched targets.
