# SRA-direct import (canonical workflow)

**This is the preferred way to get a public CLIP study onto Flow.** Flow pulls the reads
from SRA/ENA itself, so there is no local download, no `prefetch`, no `removespace` header
cleaning and no multi-gigabyte staging disk. The focus is metadata accuracy and a
header preview.

Requires **flowbio ≥ 0.12.0** (`flowbio samples import`; `project`/`pubmed` reserved). The
local-upload path is the 2xx line in `reference/stages.md`, and is the fallback for a study
absent from SRA/ENA.

Worked example throughout: **GSE215250** — Busa *et al.* 2024, *iScience*
([PMID 38495826](https://pubmed.ncbi.nlm.nih.gov/38495826/)) — 8 PARP13 eCLIP samples
(4 IP + 4 size-matched input) in HEK293T.

---

## 0. Before anything else — is the data public?

**A Data Availability statement is a promise, not a fact.** Accessions are routinely reserved
at submission and released at publication, so a named `GSE` proves only that the authors
intend to deposit. Check first; it is one request and it ends the question:

```python
from lib.accession_availability import geo_url, parse_geo_response
print(parse_geo_response(acc, fetch(geo_url(acc))).describe())
```

**Fetch the SOFT endpoint, not the accession page.** GEO's default HTML page
(`acc.cgi?acc=GSE…` with no `form`) sits behind reCAPTCHA and returns a challenge to any
agent fetch tool — which reads as "study not found" rather than as a block. `geo_url()`
builds the machine-readable form, and `curl` handles it where a fetch tool cannot:

```bash
curl -s "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE262435&targ=self&form=text&view=brief"
```

The same applies to the paper: PMC's `/bin/*.xlsx` supplementary downloads are behind a
client-side proof-of-work challenge no headless fetch clears, so a supplementary table that
holds the barcode (step 5 of the antibody search order, and the barcode fallback in
`reference/barcode-examples.md`) may need the researcher's own browser session. Say so at the
gate rather than recording "no evidence found".

AUTS2 (PMID 41278797) is why this is step 0 rather than a footnote. eCLIP of a genuinely new
protein in human neural progenitors, three accessions named in the paper — and all three
**private until 07 Aug 2029**. The embargo was discovered only after the full literature dig:
abstract, Europe PMC, PMC efetch, bioRxiv full text, methods extraction.

Then ask **the whole platform** whether the study is already there — not just the project
you are about to import into:

```python
from lib.study_already_uploaded import build_search_queries, summarise_hits, search_url
q = build_search_queries(sheet_rows, extra=["<distinctive title word>"])
print(summarise_hits({t: fetch(search_url(t)) for t in q}).describe())
```

GSE80202 was already on Flow — public, all 7 samples, paper attached — and was imported
again. The project-scoped pre-flight below ran first and said *none (clean import)*: true,
and worthless, because the target project had been created seconds earlier and was empty by
construction. It also matched on sample **name**, and the two uploads named the same samples
`Nacc1_N2A_Mm_rep1` versus `NACC1_N2A_Mm_endogenous_rep1_SRX2415967`.

Search on **accessions** (they survive inside deposited filenames) and **target proteins**.
The parameter is `q`, not `query`. `GSM…` and PubMed ids are **not indexed** and return empty
— querying them would pad a clean result with searches that can never match. Re-run against
the live platform, all 10 queries matched.

Then ask the **project** what it already holds — not a status note, not even your own:

```python
from lib.import_preflight import find_already_present, names_from_listing
present = find_already_present(sheet_rows, names_from_listing(listing))   # GET /projects/{id}/samples?count=100
```

Three outcomes, three different next moves:

| Outcome | What to do |
|---|---|
| released | proceed to step 1 |
| private, weeks away | wait, or request a reviewer token from the authors |
| private, years away | drop the study, or email the authors — do not start on the metadata |
| not found | a typo, or the accession was withdrawn |

Note the signal is the **response format**, not its wording: GEO answers in SOFT for a
released series and in HTML for an embargoed one. Sniffing for the word "private" would
misread a public series whose summary happens to discuss private data.

---

## 0a. The non-obvious API facts

These cost a debugging cycle each and are now enforced in `lib/sra_import.py`.

| # | Fact | Symptom if ignored |
|---|------|--------------------|
| 1 | **The accession must be an experiment — `SRX`/`ERX`/`DRX`, never a run (`SRR`/`ERR`)** | `HTTP 500 internal_error`, no diagnostic |
| 2 | **The sheet drops `__annotation` columns** — they are forwarded as ordinary metadata keys and discarded by the import job server-side | Import succeeds; targets and sources arrive with no annotation. `project` is fine: reserved since 0.12.0 |
| 3 | **`strandedness` is rejected for CLIP** — it is an RNA-Seq field | `422 … Not a valid attribute for this sample type` |
| 4 | **Deleting a sample is `POST /samples/{id}/delete`, verified by a 404** — use `FlowClient.delete_sample`. The `DELETE` verb returns `200` with the sample body and is **inconsistent**: it has both worked and silently done nothing | You believe a sample is gone; it is still in the project and still matches your execution filters |
| 5 | **The import silently drops `__annotation` columns** — `purification_target__annotation` and `source__annotation` are accepted and stored nowhere | Job `COMPLETED`, every read attached, and every tag and cell-line detail gone. GSE252683 lost `nFLAG` / `Flp-In T-REx` / `neuroblastoma` on all 12 samples with no error anywhere |
| 6 | **`GET /projects/{id}/samples` returns trimmed samples whose `metadata` is `{}`** — not absent, *empty* | Verifying against the listing reports every field of every sample as dropped. Fetch each sample with `GET /samples/{id}` |

Fact 4 belongs to a family worth knowing: several Flow write endpoints return `200` while
silently ignoring the request. Seen doing so: `DELETE /samples/{id}` and
`POST /data/{id}/edit {"filename": …}`. **Always re-read the resource after a mutation**
rather than trusting the status code — `flow_edit_samples.py`'s verification step exists for
exactly this reason (though it reads a top-level key while metadata is nested under
`metadata.<key>.value`, so its warnings are noisy).

Note that `samples upload` (unlike `samples import`) **does** honour `--project`, so a
locally-uploaded sample needs no separate assignment step.

Fact 3 has an upstream inconsistency worth knowing: `flowbio samples batch-template
--sample-type CLIP` may still list `strandedness` among the **required** columns, while the
import endpoint refuses it. Trust the endpoint; `FORBIDDEN_SHEET_COLUMNS` drops it.

Both accessions are needed during a run: **`SRR` for the header preview** (ENA serves
FASTQ per run) and **`SRX` for the import**. `srr_map.tsv` therefore carries both.

---

## 1. Inputs

| Input | Where from |
|-------|-----------|
| GEO series matrix | `--geo-matrix` on `02_index` / `04_annotate` |
| `srr_map.tsv` with **`gsm`, `srr`, `srx`** columns | SRA run selector / ENA filereport. `mate` and `fastq` are optional — derived on ENA's naming when absent, and needed only by the local line |
| Paper Methods excerpt | `--paper-text` — the **CLIP assay section only** |
| Flow project id | `00_setup --project-id`, or `--create-project "<name>"` to make one |
| API token | `FLOW_TOKEN` / `FLOW_API_TOKEN`, or `~/.config/flow/api-token` |

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

**Why ENA and not `fastq-dump`:** ENA renders the defline as `@<run>.<n> <original spot
name>` —

```
@SRR21863801.1 K00180:212:H7VCTBBXX:5:1101:20598:1033/1
```

— which is the form **Flow itself fetches**. That is the reason, and it is the only reason:
the preview must see the study exactly as the import will.

`fastq-dump` does **not** rewrite deflines to `@SRR…N`, and `--origfmt` prints the original
spot name alone. Measured on `SRR33628723` with sra-tools 3.2.1, `:rbc:` survives every form —
only its *position* changes:

| source | defline | UMI sits in |
|---|---|---|
| ENA `fastq_ftp` | `@SRR33628723.1 NS500784:…:1rbc:TAGGATAAA/1` | comment |
| `fastq-dump` (default) | `@SRR33628723.1 NS500784:…:1rbc:TAGGATAAA length=83` | comment |
| `fastq-dump --origfmt` | `@NS500784:…:1rbc:TAGGATAAA` | read name |
| `fasterq-dump --seq-defline '@$sn'` | `@NS500784:…:1rbc:TAGGATAAA` | read name |

**The UMI is lost at the whitespace boundary, not at dump time.** The SAM QNAME ends at the
first space, so anything in the comment is dropped at alignment — the same rule that makes
`removespace` necessary. Everything that keeps the accession prefix pushes the original
header past a space.

`fasterq-dump` therefore fixes nothing `fastq-dump` cannot: `--seq-defline '@$sn'` is
identical to `--origfmt`. Neither helps the direct line, because there **Flow does the
fetching** and gets ENA's comment form regardless.

The fallback is still not trusted, for the inverse reason: `--origfmt` removes the comment
field entirely, so `umi_is_stranded_in_comment` has no space to find and its refusal would
silently vanish. It now infers the verdict from provenance instead, and
`headers_provenance.md` records which source each run used.

The inspection feeds the same `fastq_headers.inspect_header_lines()` used by the local
path, so remote and local previews cannot diverge. Params follow the usual table in
`reference/eclip-analysis-params.md`.

GSE215250 result: no `:rbc:` → `move_umi_to_header=true`, `umi_separator=_`,
`encode_eclip=false`, `umi_header_format=NNNNNNNNNN`.

---

## 3. Metadata gate

Build the annotation as normal, then validate before importing:

- `05_metadata` → `metadata_report.md` + `metadata_issues.json`
- Any error stops the stage at exit 3; release it with `--accept-metadata` once reviewed
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
> **`samples upload` does not have this problem.** The local path sends
> `purification_target__annotation` and `source__annotation` with the sample and they arrive
> intact, so it needs no second pass. The gap is specific to `samples import`.

---

## 5. Import, poll, assign

`sra_import.sh` does all three; the import is **asynchronous** and returns a job id.

```bash
flowbio --json samples import --sheet import_sheet.csv        # -> {"id": ..., "status": "RUNNING"}
flowbio --json samples import-status --job-id <JOB>           # poll until COMPLETED
```

`import-status` returns `sample_ids` positionally matching `accessions` once `COMPLETED`.
Those ids are the input to the assignment step — **without it the samples exist but belong

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

**Check the layout first.** On SINGLE-end data there is no mate to select, and `first` or
`second` empties the samplesheet:

```python
from lib.paired_selection import check_paired_selection
r = check_paired_selection(choice, layouts={x["library_layout"] for x in ena_runs})
```

GSE75418 and GSE68800 were both submitted with `second`, inherited from a submit script
copied out of a paired-end study. The rows came out as
`MSI1_U251_Hs_WT_rep3_SRX1023997,1,,` — both read columns blank — and died at
`SAMPLE_BASE_SAMPLESHEET_CHECK` with *"Invalid number of populated columns (minimum = 3)"*,
which never mentions reads, mates or `paired`. Both executions had to be deleted and
resubmitted. ENA's `library_layout` states SINGLE or PAIRED per run, so this is answerable
before submitting.

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
| Reads | Flow pulls from SRA/ENA | fetched by hand (`wget` from ENA FTP) |
| Disk | none | full FASTQ set |
| Header check | ENA byte-range snippet | `lib/fastq_headers.py` on disk |
| Header cleaning | n/a — never uploaded locally | n/a — `removespace` runs in the clip-seq pipeline |
| Accession | **SRX** | SRR |
| Project | `project` column in the sheet (0.12.0+) | `--project-id` on upload |
| Entry point | `sra_import.sh` (`109_sheet` → `110_import`) | `upload_live.sh` (`210_upload`) |
