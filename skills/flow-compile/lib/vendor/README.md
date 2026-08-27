# `lib/vendor/` — upstream mirror, with two local patches

Everything here is mirrored from Goodwright's `flow_api` scripts. Re-vendoring overwrites it,
so the two changes below have to be reapplied by hand. Both are one line, both cause silent
data corruption when missing, and both are pinned by `tests/test_vendor_patches.py` so a
re-vendor fails CI rather than passing quietly.

## 1. `preprocessing/removespace.py` — keep the `/`

Upstream:

```python
s = text.strip().replace(' ', '_').replace('/', '_')
```

Here:

```python
s = text.strip().replace(' ', '_')
```

For a FASTQ header whose UMI rides in the comment field:

| | header after cleaning | last `_` field |
|---|---|---|
| upstream | `@SRR123.1_1:N:0:CTACGCTCTAAA_1` | `1` — constant on every read |
| here | `@SRR123.1_1:N:0:CTACGCTCTAAA/1` | `CTACGCTCTAAA/1` — varies |

UMI-collapse keys on that final field. Constant, it treats the entire library as duplicates of
one read and collapses it to near nothing, without erroring.

Spaces still have to go: the SAM QNAME ends at the first whitespace, so anything after one is
dropped at alignment. That is the whole reason this script exists.

## 2. `analysis/flowrunanalysis_flowbio.py` — `paired` is not a constant

Upstream hardcoded it in the payload:

```python
"csv_params": {"samplesheet": {"rows": rows, "paired": "both"}},
```

It decides which mate the pipeline analyses. For eCLIP the crosslink is on read 2, so `both`
produces a run that completes cleanly and puts peaks in the wrong places. It is now taken from
the pipeline params (`params.pop("paired")`) and validated against `both`/`first`/`second`,
because a wrong value here does not fail the run.

`paired` is a samplesheet setting rather than a pipeline param, which is why it is popped out
of `params` rather than sent inside it.
