# SRA-direct import (canonical workflow)

**This is the preferred way to get a public CLIP study onto Flow.** Flow pulls the reads
from SRA/ENA itself, so there is no local download, no `prefetch`, no `removespace` header
cleaning and no multi-gigabyte staging disk. What remains is metadata accuracy and a
header preview — which is where all the guardrails now sit.

Requires **flowbio ≥ 0.10.0** (`flowbio samples import`). The older local-download path
(`prefetch.sh` → `clean_fastq.sh` → `upload_live.sh`) is still documented in `WORKFLOW.md`
and is the fallback when a study is not in SRA/ENA, or when reads must be transformed
before upload (FLASH / uvCLAP UMI extraction).

Worked example throughout: **GSE215250** — Busa *et al.* 2024, *iScience*
([PMID 38495826](https://pubmed.ncbi.nlm.nih.gov/38495826/)) — 8 PARP13 eCLIP samples
(4 IP + 4 size-matched input) in HEK293T.

---

## 0. The three non-obvious API facts

These cost a debugging cycle each and are now enforced in `lib/sra_import.py`.

| # | Fact | Symptom if ignored |
|---|------|--------------------|
| 1 | **The accession must be an experiment — `SRX`/`ERX`/`DRX`, never a run (`SRR`/`ERR`)** | `HTTP 500 internal_error`, no diagnostic |
| 2 | **The sheet has no `project` column** — flowbio's `RESERVED_COLUMNS` is `(accession, name, organism, sample_type)` | Import succeeds; every sample lands **unattached** and the project shows 0 samples |
| 3 | **`strandedness` is rejected for CLIP** — it is an RNA-Seq field | `422 … Not a valid attribute for this sample type` |

Fact 3 has an upstream inconsistency worth knowing: `flowbio samples batch-template
--sample-type CLIP` still lists `strandedness` among the **required** columns, while the
import endpoint refuses it. Trust the endpoint; `FORBIDDEN_SHEET_COLUMNS` drops it.

Both accessions are needed during a run: **`SRR` for the header preview** (ENA serves
FASTQ per run) and **`SRX` for the import**. `srr_map.tsv` therefore carries both.

---

## 1. Inputs

| Input | Where from |
|-------|-----------|
| GEO series matrix | `--geo-matrix` (or `--gse`) |
| `srr_map.tsv` with **`gsm`, `srr`, `srx`** columns | SRA run selector / ENA filereport |
| Paper Methods excerpt | `--paper-text` — the **CLIP assay section only** |
| Flow project id | `--flow-project-id`, created in the Flow UI |
| API token | `FLOW_API_TOKEN`, `--token-file`, or `~/.config/flow/api-token` |

Resolve `SRX` for a BioProject in one call:

```bash
curl -s "https://www.ebi.ac.uk/ena/portal/api/filereport?accession=PRJNA889426&result=read_run&fields=run_accession,experiment_accession,library_layout&format=tsv"
```

---

## 2. Header preview (mandatory — replaces local header inspection)

`lib/sra_header_preview.py` byte-range-fetches ~500 KB of the gzipped FASTQ from the ENA
FTP mirror and decodes the first few records.

```bash
python3 -c "from lib.sra_header_preview import preview_runs, inspection_from_header_records; \
r,s = preview_runs(['SRR21863801'], n_reads=4); print(s); print(inspection_from_header_records(r).notes)"
```

**Why ENA and not `fastq-dump`:** ENA serves the *submitted* file, so the original
instrument headers survive —

```
@SRR21863801.1 K00180:212:H7VCTBBXX:5:1101:20598:1033/1
```

`fastq-dump` rewrites deflines to `@SRR…N` **even with `--origfmt`**, which silently
destroys `:rbc:` detection and would send the whole study down the wrong params branch.
`fastq-dump` is therefore only a fallback for runs ENA does not serve, and
`headers_provenance.md` records which source each run used, flagging the lossy one.

The inspection feeds the same `fastq_headers.inspect_header_lines()` used by the local
path, so remote and local previews cannot diverge. Params follow the usual table in
`reference/eclip-analysis-params.md`.

GSE215250 result: no `:rbc:` → `move_umi_to_header=true`, `umi_separator=_`,
`encode_eclip=false`, `umi_header_format=NNNNNNNNNN`.

---

## 3. Metadata gate

Build the annotation as normal, then validate before importing:

- `lib/metadata_validate.py` → `CONFIRM_METADATA.md` + `metadata_validation.json`
- Errors block until the researcher re-runs with `--accept-metadata`
- Full rules and worked traps: **`reference/metadata-accuracy-checklist.md`**

This gate matters more on the SRA-direct path than on the local one, because there is no
FASTQ on disk to sanity-check the annotation against.

---

## 4. Build the import sheet

```python
from lib.sra_import import build_import_sheet, write_import_sheet, write_import_scripts
sheet = build_import_sheet(annotation)              # raises unless every row has an SRX
path  = write_import_sheet(output_dir, sheet)
write_import_scripts(output_dir, sheet_path=path, project_id="550540342405942387")
```

Column mapping (annotation → sheet). Empty optional values are **dropped**, not written
blank — an endogenous IP's empty tag annotation must not become an empty field:

| Annotation column | Sheet column | Required |
|---|---|---|
| *(from `srr_map.srx`)* | `accession` | ✔ |
| *(constant)* | `sample_type` = `CLIP` | ✔ |
| `Sample Name` | `name` | ✔ |
| `5' Barcode Sequence` | `five_prime_barcode_sequence` | ✔ |
| `Protein (Purification Target)` | `purification_target` | ✔ |
| `Organism` | `organism` | |
| `Experimental Method` | `experimental_method` | |
| `Purification Agent` | `purification_agent` | |
| `Purification Target Annotation` | `purification_target__annotation` | |
| `Cell or Tissue` | `source` | |
| `Source Annotation` | `source__annotation` | |
| `Condition`, `Sequencer`, `Comments`, `GEO ID` | `condition`, `sequencer`, `comments`, `geo` | |

Never emitted: `project`, `strandedness`, `reads1`, `reads2`.

---

## 5. Import, poll, assign

`sra_import.sh` does all three; the import is **asynchronous** and returns a job id.

```bash
flowbio --json samples import --sheet import_sheet.csv        # -> {"id": ..., "status": "RUNNING"}
flowbio --json samples import-status --job-id <JOB>           # poll until COMPLETED
python3 lib/flow_project_assign.py --project-id <PID> --sample-ids <id1,id2,...>
```

`import-status` returns `sample_ids` positionally matching `accessions` once `COMPLETED`.
Those ids are the input to the assignment step — **without it the samples exist but belong
to no project**. `flow_project_assign.py` is idempotent: samples already in the target
project are skipped, and one failure does not abort the batch.

Timing: ~3 min for a single sample, ~30 min for 8.

---

## 6. Verify

```bash
curl -s "https://app.flow.bio/api/projects/<PID>/samples?count=50" \
  -H "Authorization: Bearer $FLOW_API_TOKEN"
```

Confirm per sample: `project` is set, `metadata.five_prime_barcode_sequence.value`,
`purification_target`, `purification_agent`, `source`. Note the REST detail view nests
metadata under `metadata.<key>.value` — a top-level lookup returns `None` and is the
reason `flow_edit_samples.py` prints spurious "verify mismatch" warnings.

Then submit analysis as usual (`reference/eclip-analysis-params.md`), remembering that one
execution covers **one genome** and **one `umi_header_format`**.

---

## SRA-direct vs local-download

| Step | SRA-direct (preferred) | Local download |
|------|------------------------|----------------|
| Reads | Flow pulls from SRA/ENA | `prefetch.sh` / `wget` |
| Disk | none | full FASTQ set |
| Header check | ENA byte-range snippet | `lib/fastq_headers.py` on disk |
| Header cleaning | n/a — never uploaded locally | `clean_fastq.sh` (`removespace.py`) |
| UMI pre-extraction | **not possible** — use local path for FLASH / uvCLAP | `umi_extract.sh` |
| Accession | **SRX** | SRR |
| Project | separate assignment step | `--project-id` on upload |
| Entry point | `sra_import.sh` | `upload_live.sh` |
