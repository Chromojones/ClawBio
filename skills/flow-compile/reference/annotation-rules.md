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
| Sample Name | `protein_cell_Hs_condition_rep_SRR` (project-specific; see YEO/FLASH guardrails in full skill) |
| Type | `CLIP` |
| Experimental Method | `iCLIP`, `eCLIP`, `PAR-CLIP`, etc. |
| 5' Barcode Sequence | From barcode resolver; UMI patterns may use `N`, `R`, `Y`, `B` |
| GEO ID | `GSM…` per row |
| PubMed ID | Series `!Series_pubmed_id` |
| Protein (Purification Target) | Gene symbol from title/characteristics |
| Organism | `Hs`, `Mm`, `Gg` only — never full scientific names |

## GSM ↔ SRR alignment

1. Index matrix columns by `!Sample_geo_accession`.
2. Map SRR via SRA run pages or curated `srr_map.tsv`.
3. Prefer GEO `Title` over weak SRA `LibraryName`.

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
