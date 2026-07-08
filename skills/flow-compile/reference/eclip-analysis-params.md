# eCLIP / seCLIP — analysis params and paired-end crosslink

## `encode_eclip` rule (flow-compile)

Derived in `lib/pipeline_params.derive_clip_pipeline_params()` after `headers.txt` review.

| Experimental method | Header has `:rbc:`? | `move_umi_to_header` | `umi_separator` | `encode_eclip` |
|---------------------|---------------------|----------------------|-----------------|----------------|
| eCLIP / seCLIP | **Yes** | `false` | `rbc:` | **`true`** |
| eCLIP / seCLIP | **No** (raw SRA) | `true` | `_` | **`false`** |
| iCLIP / FLASH / other | Yes | `false` | `rbc:` | `false` |
| iCLIP / FLASH / other | No | `true` | `_` | `false` |

**Raw SRA dumps (no `:rbc:`):** Flow Trim Galore trims adapters, UMI tools move the barcode from read sequence into the header (appended with `_`), then `umi_collapse` runs. Set `umi_header_format` from confirmed 5′ barcode (typically `NNNNNNNNNN` for Yeo/ENCODE eCLIP).

**Pre-extracted ENCODE uploads (`:rbc:` in header):** UMI already in the read name — do not re-extract; `encode_eclip=true` enables Flow’s ENCODE eCLIP handling.

Never set `encode_eclip=true` without `:rbc:` in sampled headers.

## Paired-end eCLIP — upload read 1 only (post-demux)

Commercial sequencing centers **demultiplex** pooled libraries before delivery. For Flow upload we ship **read 1 only** (`*_1.fastq.gz`); **do not upload read 2** (`File 2` empty in `annotation.csv`).

| Mate | Role |
|------|------|
| **Read 1** | cDNA crosslink signal; UMI deduplication in Flow via Trim Galore + `umi_collapse` on this mate |
| **Read 2** | Index / demux barcode only at the facility — not uploaded to Flow |

`flow_annotate.build_annotation_table()` omits `File 2` for `eCLIP` / `seCLIP`. Deduplication runs on R1 with `move_umi_to_header=true`, `encode_eclip=false` for raw SRA (no `:rbc:`).

## Paired-end eCLIP — which read has the crosslink?

Standard Yeo / ENCODE eCLIP (Blue et al. 2022; Van Nostrand et al. 2016):

| Mate | Content |
|------|---------|
| **Read 1** | cDNA insert from reverse transcription; **UV crosslink** stops RT one nucleotide before the crosslinked base → CITS / crosslink site at **5′ end of R1** |
| **Read 2** | Short index + **10 bp random barcode** (and sometimes additional index); used for PCR duplicate marking, not for crosslink signal |

Implications for Flow:

- **`crosslink_position: start`** — crosslink mapped at the 5′ end of the aligned read containing the cDNA (R1).
- **`star_params` … `--alignEndsType Extend5pOfRead1`** — already set in `pipeline_params.py`; extends alignments at the 5′ end of read 1 where the crosslink sits.
- **nf-core/clipseq** documents that paired-end CLIP is processed using **the read that carries the crosslink** with `crosslink_position` set appropriately ([nf-core/clipseq README](https://github.com/nf-core/clipseq)); for eCLIP that is read 1.

Read 2 is not used for crosslink calling in standard eCLIP pipelines; some workflows discard R2 after UMI extraction.

## GSE290281 preview (SRR32456800)

- Headers: **no `:rbc:`** → extract UMI from R2 sequence, `encode_eclip=false`, `umi_header_format=NNNNNNNNNN`.
- Layout: paired-end NovaSeq 6000, Blue 2022 SOP cited in GEO.

## References

- Blue et al. 2022 — Yeo lab eCLIP SOP ([doi:10.1038/s41596-022-00680-z](https://doi.org/10.1038/s41596-022-00680-z))
- Van Nostrand et al. 2016 — ENCODE eCLIP ([doi:10.1038/nmeth.3810](https://doi.org/10.1038/nmeth.3810))
- Boyle et al. 2023 — Skipper (GEO `data_processing` for GSE290281)
