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
| 4 | **Deleting a sample is `POST /samples/{id}/delete`** — the `DELETE` verb returns `200` with the sample body but **does nothing** | You believe a sample is gone; it is still in the project and still matches your execution filters |
| 5 | **The import silently drops `__annotation` columns** — `purification_target__annotation` and `source__annotation` are accepted and stored nowhere | Job `COMPLETED`, every read attached, and every tag and cell-line detail gone. GSE252683 lost `nFLAG` / `Flp-In T-REx` / `neuroblastoma` on all 12 samples with no error anywhere |
| 6 | **`GET /projects/{id}/samples` returns trimmed samples whose `metadata` is `{}`** — not absent, *empty* | Verifying against the listing reports every field of every sample as dropped. Fetch each sample with `GET /samples/{id}` |

Fact 4 belongs to a family worth knowing: several Flow write endpoints return `200` while
silently ignoring the request. Confirmed no-ops are `DELETE /samples/{id}` and
`POST /data/{id}/edit {"filename": …}`. **Always re-read the resource after a mutation**
rather than trusting the status code — `flow_edit_samples.py`'s verification step exists for
exactly this reason (though it reads a top-level key while metadata is nested under
`metadata.<key>.value`, so its warnings are noisy).

Note that `samples upload` (unlike `samples import`) **does** honour `--project`, so a
locally-uploaded sample needs no separate assignment step.

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

> **`samples import` silently drops the `__annotation` columns.**
> `purification_target__annotation` and `source__annotation` are accepted in the sheet
> without any error, but the created samples come back with `annotation=''` on both fields.
> Every ordinary column imports fine — only the annotation sub-fields are lost.
>
> **Always set annotations in a second pass** with `flow_edit_samples.py`
> (`POST /samples/{id}/edit`), which does apply them, and verify by re-reading the **nested**
> location `metadata.<field>.annotation` — not a top-level `<field>__annotation` key, which
> never exists. Reading the wrong place makes every row look correctly empty.
>
> Seen on GSE297587: 18 rows imported with the tag and cell-line annotation missing; a
> follow-up edit pass restored `LARP6:dNTR-nMYC` and `U87:Glioblastoma`.
>
> **`samples upload` does not have this problem.** Uploading the same sample locally with
> `--metadata-json` including `purification_target__annotation` and `source__annotation`
> stores both correctly, so the local path needs no second pass. The gap is specific to
> `samples import`.

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

### 5b. Verify the import before submitting anything

**A `COMPLETED` job is not evidence the metadata arrived** (fact 5). Read the samples back
and diff them against the sheet that produced them:

```python
from lib.import_verify import find_import_discrepancies, format_report
# one GET /samples/{id} per sample — NOT the project listing, see fact 6
found = find_import_discrepancies(sheet_rows, live_samples,
                                  project_id=PID, expect_pubmed="38182429")
print(format_report(found, total_rows=len(sheet_rows)))
```

It checks every non-blank sheet column plus the three attachments the sheet cannot carry —
`project`, `pubmed`, and whether any reads landed at all. Repair whatever it reports with
`POST /samples/{id}/edit`, which *does* honour the `__annotation` columns, then re-run it to
0 before launching the execution. Blank sheet cells are skipped, so a sparse sheet does not
demand that Flow invent values.

---

## 5a. Choosing which mate to analyse — `csv_params.samplesheet.paired`

**A sample with both mates does not have to be analysed as paired-end.** The samplesheet
`csv` param accepts a `paired` key that selects the mate:

```json
{"csv_params": {"samplesheet": {"rows": [...], "paired": "first"}}}
```

| Value | Effect |
|-------|--------|
| `"both"` | **default** — both mates go to the samplesheet; the row is paired-end (`single_end=0`) |
| `"first"` | only mate 1 reaches the samplesheet — a genuine single-end row |
| `"second"` | only mate 2 reaches the samplesheet — a genuine single-end row |

Verified on GSE290281 `LGALS3_HEK293T_Hs_IP_rep1_SRR32456801` (both mates attached), same
params, only `paired` changed — `UMITOOLS_EXTRACT` consumed:

| `paired` | input file |
|----------|-----------|
| `"first"` | `SRX27771258_SRR32456801_1.fastq.gz` |
| `"second"` | `SRX27771258_SRR32456801_2.fastq.gz` |

**This is the supported way to run a mate-selected analysis, and it removes the main reason
to ever prune a mate.** Import both reads and pick the informative one at submission time:
`"second"` for ENCODE3 paired-end eCLIP, `"first"` for seCLIP.

> **Only these three values are valid.** An unrecognised value such as `"single"` is silently
> ignored and the default (`"both"`) applies — which is why an earlier attempt with
> `paired: "single"` appeared to have no effect and led to a needless re-upload.

The vendored `flowrunanalysis_flowbio.py` hardcodes `"paired": "both"`; override it when a
study needs a specific mate.

---

## 5b. Never delete a mate — upload only the read you want

> **Deleting a mate from an existing Flow sample is destructive, in both directions.**
> Afterwards the sample, fileset and data endpoints all report a single read and look
> completely correct, but the samplesheet generator still emits the *other* slot, so every
> execution containing that sample breaks. There is no API-visible trace of the problem and
> no way to clear it. The only remedy is to delete the sample and upload the wanted read with
> `flowbio samples upload --reads1 <file>` (no `--reads2`), which creates a sample that was
> never paired.

Observed both ways:

| Deleted | Survivor | Symptom |
|---------|----------|---------|
| read 1 (GSE215250, keeping read 2) | `…_2.fastq.gz` | stays in `fastq_2`, `fastq_1` empty → `Invalid combination of columns` |
| read 2 (GSE290281, keeping read 1) | `…_1.fastq.gz` | `fastq_2` still emitted, pointing at the **deleted upload id** → row looks paired; check passes, run dies staging a missing file. Mixed with genuine single-end rows it fails as `Mixture of paired-end and single-end reads!` |

The second case is the nastier one: a batch made *entirely* of such samples passes the
samplesheet check and then stalls silently.

**Diagnostic:** submit one suspect sample alone. A genuine single-end sample reaches
`UMITOOLS_EXTRACT`; a mate-deleted one finishes with only `REMOVE_GTF_BRACKETS` and
`SAMPLE_BASE_SAMPLESHEET_CHECK`.

### The original PARP13 case (read 2 only)

`samples import` pulls **whole runs**, so a PE study arrives with both mates attached. For
ENCODE3 eCLIP the crosslink is on read 2 (`reference/eclip-analysis-params.md`), so read 1
must be removed — but deleting it is not sufficient on its own.

**The trap:** Flow's samplesheet generator assigns the mate slot from the **filename
suffix**. A lone `…_2.fastq.gz` is still placed in `fastq_2`, leaving `fastq_1` empty, and
the pipeline rejects the row:

```
ERROR: Please check samplesheet -> Invalid combination of columns provided!
Line: 'SMInput_HEK293T_Hs_antiviral_rep2,1,,/media/.../SRX17851514_SRR21863794_2.fastq.gz'
```

**No submission-time workaround fixes this.** All of these were tried against GSE215250
and none produces a usable single-end row:

| Attempt | Result |
|---------|--------|
| `csv_params.samplesheet.paired = "single"` | No effect — **`"single"` is not a valid value** and is silently ignored. The real control is `"first"`/`"second"` (§5a), which does work — but only for samples that still have both mates |
| `POST /data/{id}/edit {"filename": …}` | Returns 200 but the rename is **silently ignored** |
| `POST /data/{id}/edit {"paired": 1}` | `400 — "You can only pair multiplexed data"` |
| Row `values` with `fastq_1: <data id>`, `fastq_2: ""` | Check *passes*, but `fastq_2` is still auto-filled from the filename, so the **same file occupies both slots** → classified paired-end (`single_end=0`) with identical mates; the run stops after the check |
| Row `values` with `fastq_1: <data id>`, `fastq_2` key omitted | Identical outcome |

The nf-core check is unforgiving by design:

```python
if sample and fastq_1 and fastq_2:        # -> paired-end,  single_end = 0
elif sample and fastq_1 and not fastq_2:  # -> single-end,   single_end = 1
else: print_error("Invalid combination of columns provided!")
```

`fastq_2` must be genuinely empty, and nothing at submission time can empty a slot that
Flow filled from the `_2` filename.

**The fix is at upload time, not submission time.** A sample whose read arrived through
`samples import` carries an immutable mate association. To get a true single-end sample,
upload the read-2 file explicitly as `reads1`:

```bash
flowbio samples upload --name <sample> --sample-type CLIP \
  --reads1 <SRRxxxx_2.fastq.gz> --project <PID> --organism Hs --metadata ...
```

`--reads2` is what makes a sample paired; omitting it yields single-end, and the file lands
in slot 1 regardless of its name. This costs a download of the read-2 files (SRA-direct
cannot supply them locally), which is the standing limitation of the direct-import path for
paired-end eCLIP — see §6.

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
