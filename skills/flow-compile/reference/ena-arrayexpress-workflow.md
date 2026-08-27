# ENA / ArrayExpress CLIP workflow (SDRF-driven)

How to take a CLIP study deposited in **ENA / ArrayExpress** (accessions
`E-MTAB-*`, runs `ERR*`, samples `ERS*`, experiments `ERX*`) all the way to a
Flow.bio CLIP-Seq execution. This is the sibling of the GEO/SRA path in
`reference/stages.md`; the only real differences are (1) where accessions and barcodes
come from and (2) that reads are pulled from the **ENA FASTQ FTP** instead of
`prefetch`.

Worked example: **E-MTAB-432** — Wang *et al.* 2010, *PLOS Biology*
([PMID 21048981](https://pubmed.ncbi.nlm.nih.gov/21048981/)) — 24 TIA1 / TIAL1
iCLIP + iCLAP samples in HeLa. Full metadata:
[E-MTAB-432 SDRF (full)](https://www.ebi.ac.uk/biostudies/ArrayExpress/studies/E-MTAB-432/sdrf?full=true).

All the mandatory guardrails from `SKILL.md` still apply (barcode confirmation,
header inspection, analysis-params confirmation). This doc only records the
ENA-specific deltas.

---

## 0. Inputs from ArrayExpress

Download the **full SDRF** (`...sdrf?full=true`) — the summary SDRF omits the
`Comment[SUBMITTED_FILE_NAME]` column that carries the real barcode pattern.

Key SDRF columns:

| SDRF column | Use |
|-------------|-----|
| `Comment[ENA_RUN]` | run accession `ERR*` → FASTQ filename |
| `Comment[ENA_SAMPLE]` | sample accession `ERS*` → treat as the "GSM" key |
| `Comment[ENA_EXPERIMENT]` | `ERX*` (groups technical replicates) |
| `Comment[FASTQ_URI]` | ENA FTP download URL |
| `Comment[SUBMITTED_FILE_NAME]` | **barcode source** (see §2) |
| `Comment[BARCODE]` | short 2–3 nt library tag — **NOT the pattern to upload** |
| `Factor Value[TEST]` | method (iCLIP / iCLAP) |
| `Factor Value[IMMUNOPRECIPITATE]` | antibody / purification agent |
| `Source Name` | protein + library id for sample naming |

### Build the flow-compile inputs

flow-compile consumes a GEO-style series matrix + `srr_map.tsv`. For ENA, map:

- **`srr_map.tsv`** — one row per run: `gsm` = `ERS*`, `srr` = `ERR*`,
  `mate` = `1` (single-end here), `fastq` = `ERR*.fastq.gz`.
- **series matrix** — a minimal GEO-style matrix keyed by the `ERS*` accessions
  so `lib/geo_matrix.py` can index them like GSM columns.

> The `ERS*`→`ERR*` mapping plays the role of GSM→SRR. Everything downstream
> (`flow_annotate`, naming, params) is accession-agnostic.

### Paper metadata (mandatory)

After the annotation table is built, `flow_compile.py` always runs
`lib/paper_metadata_enrich.py` when a PubMed ID is present:

1. **Scientist** — first author full name from PubMed (not ArrayExpress contact).
2. **PI** — last author full name from PubMed (not ArrayExpress contact / iCLIP method developer).
3. **Purification Agent** — vendor + catalog from paper Methods (Europe PMC full text, or `--paper-text`).
4. **Warnings** — `ANNOTATION_WARNINGS.md` lists any row where tracked fields stay empty or generic.

**E-MTAB-432 caveat:** the curated series matrix initially carried PMID `20544596`
(wrong paper). The linked publication is PMID **[21048981](https://pubmed.ncbi.nlm.nih.gov/21048981/)**
(Wang *et al.* 2010). SDRF `Factor Value[IMMUNOPRECIPITATE]` only has
`anti-TIA1 antibody` / `anti-TIAL1 antibody` — too vague for Flow; the paper Methods specify
Santa Cruz C-20 / C-18.

---

## 1. Download FASTQs from ENA FTP

ENA serves gzipped FASTQs directly — no `prefetch`/`fasterq-dump` needed. Use the
`Comment[FASTQ_URI]` values with a guarded `wget -c` (resumes partial downloads):

```bash
wget -c -O ERR039788.fastq.gz \
  "ftp://ftp.sra.ebi.ac.uk/vol1/fastq/ERR039/ERR039788/ERR039788.fastq.gz"
```

**This is a manual step** — `flow_compile.py` does *not* emit a `wget_fastq.sh`
(the SRA `prefetch.sh` generator has no ENA equivalent). The agent writes one
`wget -c` per `Comment[FASTQ_URI]` (a short loop, or one line per run) and runs
it before re-compiling with `--fastq-dir`.

### Always verify integrity before upload

Interrupted FTP transfers produce **truncated but present** `.fastq.gz` files
that pass a size check yet fail decompression. Verify every file:

```bash
for f in *.fastq.gz; do gzip -t "$f" && echo "OK $f" || echo "CORRUPT $f"; done
```

A `CORRUPT` file (e.g. `invalid compressed data--crc error`) must be
**re-downloaded** (`wget -c` or a fresh `-O`) and re-checked with `gzip -t`
before it is uploaded. See §7 for repairing a sample already on Flow.

---

## 2. Barcodes come from the submitted filename, not `Comment[BARCODE]`

This is the single most important ENA gotcha. iCLIP/iCLAP 5′ adapters are
`<experiment barcode><random UMI>`. In E-MTAB-432 the full pattern is encoded in
`Comment[SUBMITTED_FILE_NAME]`, **not** in the short `Comment[BARCODE]` tag:

```
iCLIP_pG-Beads_Hela_notgiven_hu_CANNN_20090724_LUe4_3.fq.gz
                                  ^^^^^  <- barcode pattern = CANNN
```

Parse the pattern between `_hu_` and the date:

```python
import re
re.search(r"_hu_([ACGTN]+)_\d{8}_", submitted_filename).group(1)   # -> "CANNN"
```

- `Comment[BARCODE]` = `CA` (2 nt library tag) — **do not upload this**.
- `Comment[SUBMITTED_FILE_NAME]` → `CANNN` = 2 fixed nt + 3 `N` UMI — **this is
  the `5' Barcode Sequence`** written to the annotation and the sample.

Confirm barcodes through the normal hook (`CONFIRM_BARCODES.md` /
`barcode_proposals.json` → `confirmed`). Present the submitted-filename string as
the evidence quote.

### Execution grouping by UMI length

The `N`-run length becomes `umi_header_format`, and Flow requires **one execution
per distinct `umi_header_format`**. E-MTAB-432 split into two groups:

| Group | Pattern shape | `umi_header_format` | n |
|-------|---------------|---------------------|---|
| 2 nt tag + 3 N | `TGNNN`, `GANNN`, `CANNN`, … | `NNNNN` | 16 |
| 3 nt tag + 4 N | `GTTNNNN`, `GCCNNNN`, … | `NNNNNNN` | 8 |

Embed the pattern in the sample name so a name regex can select each group at
submission time, e.g. `TIA1_Hs_HeLa_GAANNNN_LUd15_ERR039788`.

---

## 3. FASTQ header inspection (unchanged, still mandatory)

Run `lib/fastq_headers.py` → `headers.txt` on the downloaded reads.

- E-MTAB-432 headers are plain Illumina GAII (`@ERR039778.1 HWI-EAS350_...`) with
  **no `:rbc:`** — the UMI is still in the read **sequence** (read 5′ prefix
  matches the barcode pattern, e.g. `ERR039788` → `GAA...`).
- Therefore `move_umi_to_header=true`, `umi_separator=_`, `encode_eclip=false`,
  and `umi_header_format` = the `N`-run length for the group (§2).

Never set `encode_eclip=true` or hardcode `NNNNN` without this header check.

---

## 4. Annotation

`lib/flow_annotate.py` builds `annotation.csv` as usual. ENA specifics:

- `5' Barcode Sequence` = the submitted-filename pattern (`CANNN`, `GTTNNNN`, …).
- `Sample Name` embeds protein, organism, cell line, **barcode pattern**, library
  id, and run: `TIA1_Hs_HeLa_TGNNN_LUd3_ERR039778`.
- `Comments` = the full `Comment[SUBMITTED_FILE_NAME]` (provenance).
- `Organism` still normalised to `Hs`/`Mm`/`Gg` (`lib/organism.py`).
- iCLAP samples → `Experimental Method = iCLAP`, `Purification Agent = iCLAP (TAP tag)`.
- pG-bead / no-antibody controls → protein `SMINPUT`, `Purification Agent = no antibody`.

---

## 5. Upload

Standard vendored upload (single-end, one file per run):

```bash
python3 lib/vendor/flow_api/upload/uploadsample_flowbio_v6.py \
  --input annotation.csv --rows 1-24 \
  --project-id <FLOW_PROJECT_ID> --base-dir fastq_files
```

`--rows N` re-uploads a single 1-indexed data row (used in §7).

---

## 6. Submit one analysis per UMI group

For each `umi_header_format` group, write a params JSON and submit filtered by a
sample-name regex:

```bash
python3 lib/vendor/flow_api/analysis/flowrunanalysis_flowbio.py \
  --pid <FLOW_PROJECT_ID> \
  --filter sample_name '_(GTTNNNN|GGGNNNN|GCCNNNN|GAANNNN|ATCNNNN|ACTNNNN)_' \
  --params-json params_NNNNNNN.json -n 1 --yes
```

`params_NNNNNNN.json` (7-mer group):

```json
{
  "move_umi_to_header": "true",
  "umi_separator": "_",
  "skip_umi_dedupe": "false",
  "crosslink_position": "start",
  "encode_eclip": "false",
  "umi_header_format": "NNNNNNN",
  "star_params": "--outFilterMultimapNmax 100 ... --alignEndsType Extend5pOfRead1 --twopassMode Basic"
}
```

The 5-mer group uses the same JSON with `umi_header_format: "NNNNN"` and a regex
matching the 2 nt + 3 N patterns.

---

## 7. Repairing a corrupted / re-uploaded sample

If a FASTQ was corrupted (§1) and its sample was already uploaded:

1. Re-download and verify with `gzip -t`.
2. Remove the bad sample from the Flow project (UI or API).
3. Re-upload just that row: `uploadsample_flowbio_v6.py --input annotation.csv --rows <N> ...`.
4. Re-submit the affected UMI group (§6); the name-regex filter picks up the new
   sample id automatically.

## Post-upload metadata / name / barcode edits

To fix `name`, `five_prime_barcode_sequence`, comments, or purification fields on
samples already on Flow, use the vendored editor rather than re-uploading:

```bash
python3 lib/vendor/flow_api/metadata/flow_edit_samples.py \
  --project-id <FLOW_PROJECT_ID> --match-name --edits edits.csv --dry-run
```

`edits.csv` (matched by accession embedded in the sample name):

```csv
accession,name,five_prime_barcode_sequence,comments
ERR039788,TIA1_Hs_HeLa_GAANNNN_LUd15_ERR039788,GAANNNN,iCLIP_..._GAANNNN_..._4.fq.gz
```

For bulk purification-agent / annotation corrections driven by a paper's Key
Resources table, use the pull → propose → apply → push chain in
`lib/vendor/flow_api/metadata/` (see that directory's entries in
`lib/vendor/flow_api/README.md` and the `update-sample-metadata` skill).

---

## ENA vs GEO cheat-sheet

| Step | GEO/SRA path | ENA/ArrayExpress path |
|------|--------------|-----------------------|
| Metadata | series matrix + SraRunTable | full SDRF (`sdrf?full=true`) |
| Sample key | `GSM*` | `ERS*` |
| Run id | `SRR*` | `ERR*` |
| Download | `prefetch.sh` (SRA, generated) | manual `wget -c` per `Comment[FASTQ_URI]` (not generated) |
| Barcode source | GEO `data_processing` / paper methods | `Comment[SUBMITTED_FILE_NAME]` |
| Integrity | (SRA validated) | **`gzip -t` every file** |
| Everything else | identical | identical |
