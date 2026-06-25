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
| PubMed ID | Series `!Series_pubmed_id` |
| Protein (Purification Target) | Gene symbol from title/characteristics |
| Organism | `Hs`, `Mm`, `Gg` only — never full scientific names |
| Purification Target Annotation | Tag on protein (`c3xFLAG-HBH`); API key `purification_target__annotation`; displays as `GENE:annotation` |

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
| Flow project | CLI `--flow-project-id` | User creates project in Flow UI |

## Barcode source priority

1. Curated override (alert config)
2. `!Sample_extract_protocol_ch1` / `!Sample_data_processing` (adapter grammar)
3. `!Sample_description`
4. `!Sample_characteristics_ch1` (`3' tag`, `5' tag`)
5. Paper methods text (manual `--paper-text`)

## Flow API metadata keys

`uploadsample_flowbio_v6.py` maps `5' Barcode Sequence` → `five_prime_barcode_sequence`,
`Protein (Purification Target)` → `purification_target`. Flow sample JSON may expose
`protein_target__annotation` (double underscore) for enriched targets.
