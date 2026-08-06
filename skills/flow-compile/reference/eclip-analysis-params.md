# eCLIP — read structure, barcodes and analysis params

**Read this before annotating or analysing any eCLIP study.** Paired-end eCLIP and
single-end eCLIP (seCLIP) have *different read structures*, and the mate that carries the
crosslink is **not** the same in both. Getting this wrong silently analyses the wrong end
of the molecule.

> **Correction (2026-08):** an earlier version of this document said the crosslink is always
> at the 5′ end of read 1. For **ENCODE3 / Van Nostrand 2016 paired-end eCLIP the crosslink
> is on read 2** — confirmed by the Yeo lab's own processing (`samtools view -f 128`) and by
> `eclipdemux`. A first revision then over-corrected to "PE eCLIP → read 2" for all eCLIP;
> that is also wrong. **ENCODE4 / Blue 2022 libraries are single-end and use read 1** even
> when deposited as PAIRED. Establish the SOP era first — see §0.

---

## 0. First decide which SOP era the study is — it flips the answer

**Do not apply a blanket "eCLIP → read 2" rule.** Which mate carries the crosslink depends
on the protocol generation, and the two are easy to tell apart.

| SOP | Skipper `protocol` | Layout | Crosslink read | Worked example |
|-----|--------------------|--------|----------------|----------------|
| **Van Nostrand 2016** | `ENCODE3` | paired-end | **read 2** | GSE215250 (PARP13) |
| **Blue 2022** | `ENCODE4` | single-end | **read 1** | GSE290281 (tethered RBP screen) |

[Skipper](https://github.com/YeoLab/skipper) — the Yeo lab's own pipeline — makes this
explicit. Its **default** config (both `example/Example_config.yaml` and the lab-internal
example) reads:

```yaml
protocol: ENCODE4   # ENCODE4 for single end, ENCODE3 for paired end.
UMI_SIZE: 10
INFORMATIVE_READ: 1
```

So a GEO record saying *"analyzed using Skipper with **default parameters**"* is telling you
`INFORMATIVE_READ = 1` — **read 1**, with a 10 nt UMI. A study citing Blue 2022 that is
deposited as PAIRED in SRA is still an ENCODE4 single-end library; the second mate is not
used.

### Free empirical test (no protocol text needed)

Sample a few thousand read-1 sequences and take per-position base composition:

| Read 1 positions 1–7 | Meaning | Use |
|----------------------|---------|-----|
| **Low entropy** (collapses to 1–2 bases, e.g. `AAGCAAT`/`GGCTTGT`) | inline demux barcode → **ENCODE3** | **read 2** |
| **High entropy** (~1.9–2.0, no fixed prefix) | no inline barcode → **ENCODE4** | **read 1** |

GSE290281 read 2 additionally begins with a constant `TCGATATC` and carries ~16% poly-G
(NovaSeq dark reads) — the signature of a mate that is not informative.

---

## 1. Which mate carries what (ENCODE3 / paired-end)

| | Paired-end eCLIP | seCLIP (single-end) |
|---|---|---|
| **Read 1** | `[inline barcode ~7 nt][insert]` — the **demultiplexing** barcode | `[randomer N5/N10][insert]` |
| **Read 2** | `[randomer N5/N10][insert starting at the crosslink]` | *(none)* |
| **Crosslink** | **5′ end of read 2** | 5′ end of read 1 |
| **UMI / dedup** | randomer on **read 2** | randomer on read 1 |
| **Upload to Flow** | **read 2** | read 1 |

The RT stops one nucleotide 3′ of the crosslinked base; the ssDNA adapter (`rand3Tr3`)
carrying the randomer is ligated to the cDNA 3′ end, so the mate that reads *from the
adapter inward* (read 2 in PE) begins at the crosslink once the randomer is trimmed.

Van Nostrand *et al.* 2016 ([PMC4887338](https://pmc.ncbi.nlm.nih.gov/articles/PMC4887338/)):

> "the ssDNA adapter (rand3Tr3) contains an inline random-mer (**either N5 or N10**) to
> distinguish whether two identical sequenced reads indicate two unique RNA fragments or
> PCR duplicates"
> "After standard HiSeq demultiplexing, eCLIP libraries with distinct inline barcodes were
> demultiplexed using custom scripts, and **the random-mer was appended to the read name**"

Authoritative implementation — [YeoLab/eclipdemux `demux.py`](https://github.com/YeoLab/eclipdemux/blob/master/eclipdemux_package/demux.py):

```
trim barcode  from front of 1st read in pair
trim randomer from front of 2nd read in pair
```
```python
randomerseq = fastqread2["sequence"][0:randomerlength]   # randomer lives on READ 2
parser.add_option("--length", dest="randomer_length", default=10)  # legacy default was 3
```

**Randomer length: default `10` (N10)**; N5 and the legacy 3 also occur. Confirm per study —
`umi_header_format` must match.

---

## 2. The 7 nt inline barcode (read 1, PE only)

Barcode identities live in the Yeo lab reference set **`yeolabbarcodes_20170101.fasta`**,
referenced by GEO `data_processing` blocks and consumed by `eclipdemux`. Commonly seen
7-mers:

| Id | Sequence | | Id | Sequence |
|----|----------|-|----|----------|
| A01 | `AAGCAAT` | | C01 | `ACAAGTT` |
| B06 | `GGCTTGT` | | D8f | `TGGTCCT` |

- `eclipdemux` reserves the ids **`NIL`**, `SHO`, `unassigned`, `tooshort`. **`NIL` means
  "no inline barcode"** — this is what size-matched inputs (SMInput) carry, and GEO writes
  it verbatim as `inline barcodes: Nil`.
- A single IP sample often carries **two** inline barcodes (e.g. `A01, B06`) pooled in one
  run. Per Van Nostrand 2016 these are the *same* biological sample: "eCLIP datasets with
  multiple inline barcodes were merged at the usable read stage" — the Yeo pipeline merges
  the PCR-deduped BAMs (`samtools merge`). They do **not** need splitting into two Flow
  samples.

**Verifying the barcode empirically** (cheap and decisive): sample a few thousand read-1
sequences and take per-position base composition. An intact inline barcode shows positions
1–7 collapsing to one or two bases (entropy ≪ 2.0), then jumping to ~2.0 at position 8.
An `NIL` input shows ~2.0 at *every* position. See the worked example in §5.

---

## 3. Has the barcode/UMI already been extracted? — three header states

This single check drives every parameter. **Inspect headers before choosing params.**

| Header looks like | Meaning | Params |
|---|---|---|
| `@…:1101:20598:1033/2` — plain instrument name, read 1 still starts with the 7-mer | **Raw, not demultiplexed** | `move_umi_to_header=true`, `umi_separator=_`, `umi_header_format=` N×randomer length, `encode_eclip=false` |
| `@NNNNNNNNNN:K00180:212:…` — randomer **prepended** to the title | Processed by current **`eclipdemux`** | `move_umi_to_header=false`; UMI already in the name |
| `@…:1101:1445:2149:rbc:CACTTG 1:N:0:ATCACG` — `:rbc:` **mid-header** | **ENCODE portal download** (pre-extracted) | `move_umi_to_header=false`, `umi_separator=rbc:`, **`encode_eclip=true`** |
| `@…:1101:1445:2149:rbc:CACTTG` — `:rbc:` at the **end** of the header | UMI extracted, but **not** ENCODE layout (typical **iCLIP**) | `move_umi_to_header=false`, `umi_separator=rbc:`, **`encode_eclip=false`** |

> **`encode_eclip` keys off *where* `:rbc:` sits, not merely that it is present.**
> `encode_eclip=true` is for the ENCODE layout, where `:rbc:` appears **mid-header** — i.e.
> the read name continues after the randomer (a trailing ` 1:N:0:INDEX` comment field
> follows). Most **iCLIP** samples carry `:rbc:` at the **end** of the header and must use
> `encode_eclip=false`. Presence alone is not sufficient evidence; check the position.

> **Paired-end eCLIP files downloaded from the ENCODE portal already have the barcode
> extracted into the read header** (`:rbc:` form). Do not re-extract them — set
> `encode_eclip=true`. Files pulled from SRA/ENA for the *same* experiment are usually
> **raw** and need extraction. Always check; do not assume from the accession.

Note `lib/fastq_headers.py` currently detects only the `:rbc:` form. The
`RANDOMER:title` form emitted by current `eclipdemux` is a **third** state — if you meet
it, treat it as already-extracted and set `move_umi_to_header=false`.

Never set `encode_eclip=true` without `:rbc:` in sampled headers.

---

## 4. Parameter derivation

| Param | Rule |
|-------|------|
| `move_umi_to_header` | `true` when the randomer is still in the read sequence; `false` once it is in the header |
| `umi_separator` | `_` for raw extraction; `rbc:` for ENCODE pre-extracted |
| `umi_header_format` | all-`N` of the randomer length — **`NNNNNNNNNN`** for the eclipdemux default |
| `encode_eclip` | `true` **only** for `:rbc:` ENCODE-style headers |
| `crosslink_position` | `start` — 5′ end of the uploaded read (read 2 for PE eCLIP) |
| `skip_umi_dedupe` | `false` (dedup is the whole point of the randomer) |
| `star_params` | `--alignEndsType Extend5pOfRead1` extends the 5′ end of the *uploaded* read; correct when read 2 is uploaded as the single read |

The `5' Barcode Sequence` **metadata** field is a literal `ACGTN` string; the execution
`umi_header_format` is always a plain run of `N` of the same length. They are different
things and must not be interchanged.

---

## 5. Worked example — GSE215250 (PARP13 eCLIP, PMID 38495826)

8 samples: 4 PARP13 IP + 4 matched SMInput, HEK293T, 2×55 bp.

Empirical read-1 composition (4,000 reads each) proved the deposited FASTQs are **raw**:

| Sample | GEO `inline barcodes` | Measured read-1 prefix | Entropy pos 1–7 |
|---|---|---|---|
| WTSS1 IP | `A01, B06` | `AAGCAAT` 33.0% + `GGCTTGT` 29.4% | 1.13 → 0.55 |
| WTSS2 IP | `C01, D8f` | `ACAAGTT` 37.2% + `TGGTCCT` 31.2% | 1.10 → 0.60 |
| WTSS1 INPUT | `Nil` | none (top 7-mer 1.8%) | **1.90–1.99** |

`:rbc:` scan: **0 hits in ~50,000 headers per mate**, both reads, IP and input → not
demultiplexed, randomer still in read 2's sequence.

GEO `data_processing` corroborates the whole chain:

> "Reads were demultiplexed and umi-extracted according to their inline barcode
> (`yeolabbarcodes_20170101.fasta`) with custom scripts (`eclipdemux`)"
> "Uniquely mapped reads were removed of PCR duplicates with … `barcodecollapsepe.py`"
> "PCR-deduped BAM files from data with multiple inline barcodes were **merged**"
> "**R2 was extracted from aligned reads using `samtools view -f 128`**"

Resulting params: `move_umi_to_header=true`, `umi_separator=_`,
`umi_header_format=NNNNNNNNNN`, `encode_eclip=false`, `crosslink_position=start`,
`skip_umi_dedupe=false`.

---

## 6. Interaction with SRA-direct import

`flowbio samples import` pulls **whole runs** — for a PE study that means both mates are
attached to the sample, with a mate association Flow derives from the filename and which
cannot be changed afterwards.

**Deleting read 1 does not yield a single-end sample.** The surviving `_2` file stays in the
`fastq_2` slot, `fastq_1` comes up empty, and the nf-core samplesheet check rejects the row.
Forcing `fastq_1` at submission time only puts the same file in *both* slots, which is then
classified paired-end with identical mates and stalls. The full list of failed workarounds
is in `reference/sra-direct-import.md` §5b.

**So paired-end eCLIP must use the local-download path:** fetch the read-2 FASTQs from ENA
FTP and upload them with `flowbio samples upload --reads1 <read2 file>` (omitting
`--reads2`), which assigns slot 1 explicitly and produces a genuine single-end sample.

Record the choice in the sample `Comments` — that read 2 is the uploaded read is not
recoverable from the Flow record otherwise.

---

## References

- Van Nostrand *et al.* 2016, *Nat. Methods* — eCLIP ([PMC4887338](https://pmc.ncbi.nlm.nih.gov/articles/PMC4887338/), [doi:10.1038/nmeth.3810](https://doi.org/10.1038/nmeth.3810))
- Blue *et al.* 2022 — Yeo lab eCLIP SOP ([doi:10.1038/s41596-022-00680-z](https://doi.org/10.1038/s41596-022-00680-z))
- [YeoLab/eclipdemux](https://github.com/YeoLab/eclipdemux) — `demux.py`, barcode reference `yeolabbarcodes_20170101.fasta`
- [YeoLab/eclip](https://github.com/yeolab/eclip) — full processing pipeline
- Busa *et al.* 2024, *iScience* — worked example ([PMID 38495826](https://pubmed.ncbi.nlm.nih.gov/38495826/))
