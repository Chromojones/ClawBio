# Failures

One line per incident, pointing at the test that encodes it. The tests carry the full
narrative; this is the index. Every entry cost real time on a real study.

Module docstrings link here by anchor.

## Read structure and protocol

### eclip-header-states
An eCLIP FASTQ arrives in four states, and `inspect_header_lines` returned two booleans that
could not tell a raw header from one whose randomer `eclipdemux` had already prepended. Both
answered `(False, False)`. Deriving parameters from that re-extracts five bases of real insert
and deduplicates on sequence that is not the UMI. Nothing errors.
→ `tests/unit/test_header_state.py`

### eclip-mate-filenames
Paired-end eCLIP carries the crosslink on read 2. The orchestrator promoted that mate twice;
the stage rewrite promoted it zero times, which is quieter — an eCLIP study then uploads the
barcode-only read 1 and every peak lands wrong. Proving a function idempotent is worthless
while nothing calls it.
→ `tests/unit/test_eclip_mate_idempotence.py`

### protocol-detection
`PAR-iCLIP` must be tested before both `PAR-CLIP` and `iCLIP`: `par[\s-]?clip` cannot match it,
and the bare `iclip` pattern then matches the tail of the same word. GSE207656 read as `iCLIP`
for months. `is_eclip_method` also existed twice with two sources of truth, deciding which mate
carries the crosslink.
→ `tests/unit/test_protocol.py`

### read-structure
Composition finds the barcode/UMI boundary but cannot settle the UMI's last base. On GSE131210
position 13 measured 7.9% off even — between random (~4%) and genomic (12–21%) — because it is
the terminal N of a synthesized oligo. So the layout is a RANGE, with no `umi_len` attribute to
tempt anyone, and the length comes from the authors' pipeline config.
→ `tests/unit/test_inline_layout_boundary.py`, `tests/unit/test_umi_params_coherent.py`, `tests/unit/test_umi_header_safety.py`

## Import and upload

### import-sheet-columns
"The import sheet has no `project` column" was true of flowbio 0.10.0, stated in five places,
and false from 0.12.0, which reserves `project` and `pubmed`. Annotations are still discarded
by the import job — the client forwards `__annotation` as an ordinary metadata key exactly as
the upload path does, so the loss is server-side. A colon does not carry one either: Flow
renders `value:annotation` but stores the colon literally.
→ `tests/unit/test_import_sheet_columns.py`

### import-check
Preflight, verify and repair each held their own copy of "which columns are not metadata",
under two names. Both went stale the hour `project` became reserved, and every sample in a
study was then reported as `project dropped by the import` while the repair plan queued an
edit re-setting a project that was already right.
→ `tests/unit/test_import_check.py`

### import-guards
The size ceiling counted the accession as written. Asking Flow for a run imports its whole
parent experiment — `SRR3175580` delivered all four runs of `SRX1590001`, 10.07 GB — so a sheet
of runs measured far below what it would transfer, and the 132.7 GB ceiling GSE63262 taught us
could be walked straight past. The module that knew about expansion and the one that enforced
the ceiling were written a week apart and never introduced.
→ `tests/unit/test_import_guards.py`

### study-check
`find_already_present` compares the sample names in our own sheet, which we choose. A study
uploaded earlier under a different convention reports "none, clean import" and is uploaded
twice. Searching Flow for the study's own identifiers catches what name comparison cannot.
→ `tests/unit/test_study_already_uploaded.py`

### flow-client
`project_id_of` existed three times because the API returns the field nested from
`GET /samples/{id}` and bare from listings. The third copy handled only the nested shape and
raised `AttributeError` on the other — inside the repair stage, whose input is a listing.
→ `tests/unit/test_flow_client.py`

## Gates and state

### approval-hooks
Barcodes and analysis parameters are hard stops. Both were once warnings that printed and
continued, which is how an unapproved barcode could reach an upload. A gate exits 3, writes its
evidence, names its release flag, and does not satisfy a prerequisite — without that last part
it is decorative.
→ `tests/stages/test_gates.py`

### params-confirmation
The confirmation gate compared two JSON files with `cmp -s`. Identical parameters differ
byte-for-byte on key order or indentation, so a correct run could be refused for a reformat —
and a gate that blocks correct runs teaches its operator to route around it. `cmp` also reports
no difference between two files that are equally wrong.
→ `tests/unit/test_params_confirmation.py`

### state-contract
The local path required running the same command three times, for a specific reason: header
cleaning renamed every read to `*.cleaned.fastq.gz`, so the annotation sheet's `File` column was
stale the instant it ran and had to be rebuilt against the new names. Re-executing the whole
command was the mechanism for that rebuild. Since `removespace` moved into the clip-seq
pipeline nothing renames anything locally, so the annotation is built in one pass — held there
by a test that exactly one stage writes it. `state.json` covers the general case: a digest match
alone is not "done", the declared outputs must still exist.
→ `tests/unit/test_state.py`, `tests/stages/test_resume.py`, `tests/stages/test_single_pass.py`

### stage-contract
Sixteen scripts is more surface than one command, and the trade only pays if the guarantee
lives in `stages/_common.py` and is checked by a loop over whatever is in `stages/`. A
per-stage suite would pass while a new stage skipped `require()` or invented its own exit
codes.
→ `tests/stages/test_stage_contract.py`

### driver
`flow_compile.py` was 1,026 lines whose control flow was the dependency graph. What survives is
the order and `--status`/`--next`, because the stage model's real cost is losing your place.
→ `tests/unit/test_driver.py`

### result-type-sprawl
Seventeen result types reduced to two shapes, `Finding` and `Verdict`, with four `Check`
dataclasses and five copies of the severity constants between them. `Finding` keeps
`__getitem__` because the tests index positionally.
→ `tests/unit/test_results.py`

## Vendored code

### vendor-patches
`lib/vendor/` is an upstream mirror; a re-vendor reverts local changes silently. Two matter.
`removespace` must keep `/`: replacing it makes the last `_` field a constant `1` on every
read, and UMI-collapse then treats the whole library as duplicates of one read. And `paired`
must not be hardcoded to `both`: it decides which mate is analysed, and a wrong value produces
a clean-looking run with peaks in the wrong places.
→ `tests/unit/test_vendor_patches.py`, `lib/vendor/README.md`
