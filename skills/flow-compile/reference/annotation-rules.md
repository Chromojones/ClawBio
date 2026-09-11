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
| Scientist | **First author** from the linked PubMed record (`paper_metadata_enrich`, in `04_annotate`). Seeded from the GEO contact, which stays if the fetch fails or the run is `--offline` — check it at the metadata gate |
| PI | **Last author** from the linked PubMed record, with the same GEO-contact fallback |
| PubMed ID | Series `!Series_pubmed_id` (verify against publication — ArrayExpress deposits may be wrong) |
| Protein (Purification Target) | Gene symbol from title/characteristics |
| Organism | A Flow organism code (`Hs`, `Mm`, `Rn`, `Dr`, `Dm`, …; the table is `lib/organism.py`) — never a Latin or common name |
| Purification Target Annotation | Tag on protein (`c3xFLAG-HBH`); API key `purification_target__annotation`; displays as `GENE:annotation` |
| Purification Agent | Full antibody string from **paper Methods** when GEO/SDRF is vague; format `Mouse Anti-TARGET (Vendor Catalog)` — resolved in `04_annotate` when a PubMed ID is present; warnings in `annotation_warnings.json` |

## eCLIP / seCLIP — the crosslink mate

In paired-end eCLIP the crosslink mate is **read 2, not read 1**: read 1 holds only the 7 nt
inline demultiplexing barcode, while **read 2 carries the randomer (N5/N10) followed by the
crosslink** — the Yeo pipeline extracts it with `samtools view -f 128`, and `eclipdemux` trims
the randomer from "the front of 2nd read in pair". On the direct line both mates are imported
and `108_params` selects read 2 with `paired=second`. For a local upload,
`apply_eclip_crosslink_mate_filenames` promotes File 2 → File so read 2 is the file sent.

**seCLIP** is genuinely single-end: read 1 is the only read and carries the crosslink.

The UMI parameters follow the **header state**, not the mere presence of `:rbc:` — a raw read
is extracted (`move_umi_to_header=true`), a prepended randomer is not. `108_params` derives
them; the four states and the literature are in `reference/eclip-analysis-params.md` §3.

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
| Analysis params | `pipeline_params.json` | `108_params` derives `move_umi_to_header`, `umi_header_format`, `paired`; released with `--accept-params` |
| Paper metadata | `annotation_warnings.json` | After annotation build: Scientist = first author; PI = last author; purification agents from paper Methods/PMC; review warnings for empty/generic fields |
| Flow project | `00_setup --project-id` or `--create-project` | Adopted or created at setup |

## Barcode sources

The search order, worked examples and the supplementary-materials fallback live in
`reference/barcode-examples.md`. `03_barcodes` gathers evidence from the series matrix, the
attached `--paper-text` and GEO sample pages, and proposes; the researcher confirms.

## Flow API metadata keys

`uploadsample_flowbio_v6.py` and `sra_import.COLUMN_MAP` map `5' Barcode Sequence` →
`five_prime_barcode_sequence`, `Protein (Purification Target)` → `purification_target`, and
`Purification Target Annotation` → `purification_target__annotation`, which Flow stores nested at
`metadata.purification_target.annotation`.
