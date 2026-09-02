# Metadata accuracy checklist (guardrails)

The checklist a researcher — or any model driving this skill — must satisfy before a CLIP
study is uploaded to Flow. It exists because three fields are **not reliably present in
GEO** and were previously left to the agent's judgement, producing different answers from
different models on the same study:

| Field | Flow key | Why it drifts |
|-------|----------|---------------|
| Purification Agent | `purification_agent` | Usually absent from GEO; papers list several antibodies per protein (Western vs IP) |
| Cell or Tissue | `source` | GEO `source_name_ch1` is often a supplier phrase or a generic descriptor |
| Purification Target Annotation | `purification_target__annotation` | Tag (GFP/FLAG/V5…) is implied by the construct, never stated as a field |

Enforcement is **code, not prose**: `lib/metadata_validate.py` validates every row and
writes `CONFIRM_METADATA.md` + `metadata_validation.json`. Errors block the pipeline until
the researcher re-runs with `--accept-metadata`. This document is the *reasoning* behind
those checks — read it when the validator flags something and you must decide what the
right value actually is.

Related: `reference/annotation-rules.md` (all columns), `reference/sra-direct-import.md`
(the preferred upload path), `SKILL.md` (hard stops).

---

## 0. The one rule that prevents most errors

> **Every metadata value must come from a named source you can quote — a GEO field, an SDRF
> column, or a specific sentence in the paper. If you cannot quote it, leave it empty and
> let the gate flag it. Never fill a field to make a warning go away.**

The agent investigates and proposes; the scripts validate and format; the researcher
approves. An agent that silently invents a plausible antibody is worse than an empty field,
because an empty field is caught and a plausible lie is not.

---

## 1. Purification Agent (the antibody)

### Search order

| # | Source | Notes |
|---|--------|-------|
| 1 | **Paper Methods, the sentence naming the assay** | `eCLIP was performed … using anti-PARP13 antibody (Thermo Fisher, PA5-31650)` — **authoritative** |
| 2 | Paper Key Resources / Reagents table | Only to resolve vendor + catalog for the antibody already identified in step 1 |
| 3 | GEO `!Sample_characteristics_ch1` — `antibody:` / `clip antibody:` | Verbatim after the colon |
| 4 | ENA SDRF `Factor Value[IMMUNOPRECIPITATE]` | Usually too vague ("anti-TIA1 antibody") — escalate to the paper |
| 5 | **Supplementary materials** — reagent/antibody supplementary tables, supplementary methods PDFs, a Key Resources Table read for *identification* this time | The final fallback when 1–4 name no reagent. Older papers and journals with terse Methods routinely push the antibody list into a supplement; GSE131210's tag construct came from primary sources outside the paper text. Quote the supplementary file and row as the evidence |

Step 5 before step "give up": the bare vendor-less form (below) is only defensible after the
supplement has actually been opened — "the Methods don't say" is not the same as "the paper
doesn't say". The step-1 precedence still holds throughout: a supplementary table row for the
right assay never overrides a Methods sentence naming a different reagent, and **never take
the first antibody listed for the protein** applies with extra force in a Key Resources Table,
which lists every reagent in the paper, not just the CLIP one.

`extract_antibodies_from_text()` (`lib/paper_metadata_enrich.py`) implements this: it
buckets matches by sentence and **antibodies in a sentence naming the CLIP assay override
antibodies found anywhere else**.

### Format

Canonical: `<Species> Anti-<TARGET> (<Vendor> <Catalog>)` — e.g.
`Rabbit Anti-PARP13 (Thermo Fisher PA5-31650)`. Species is omitted when neither the paper nor
the vendor catalog gives it (see *Host species* below): `Anti-PARP13 (Thermo Fisher PA5-31650)`.

`normalize_purification_agent()` collapses casing, comma, and `cat#` variants onto this one
spelling, so it does not matter how the model types it — but it **must** include vendor and
catalog, or it is rejected.

### When no catalog reagent exists — the bare form, provenance in Comments

Some antibodies cannot be bought. Tissue CLIP and pre-2015 studies routinely use reagents
shared between labs, so there is no vendor and no catalog number to cite. For these the agent
is the **bare canonical form** and the provenance is recorded in **Comments**:

| Study | Evidence | Agent | Comments carry |
|-------|----------|-------|----------------|
| E-MTAB-1008 (Sugimoto 2012) | Methods: *"immunoprecipitated Nova protein using an anti-Nova antibody"*; Acknowledgements: *"thank **Robert B Darnell** for sharing the anti-Nova antibody"* | `Anti-NOVA` | `gift from Robert B Darnell` |

Keeping provenance out of the agent keeps that field a controlled vocabulary — one spelling
per reagent — while losing nothing. A `(gift: X)` parenthetical typed into the agent is
**migrated out** by `normalize_purification_agent()` rather than accepted, so there is exactly
one convention on Flow.

Two things still hold:

1. **Every vendor-less agent warns.** The researcher confirms at the hook that the Methods and
   Acknowledgements really name no purchasable reagent. Reach for the bare form only after the
   search order above has genuinely come up empty.
2. **The vendor-less *prose* forms stay rejected** — `NOVA antibody`, `anti-NOVA antibody`,
   `V5-antibody`, `DHX9-mAb`. Those are scraped phrasings that identify no reagent and signal
   an unfinished lookup, which is a different failure from a genuine gift antibody.

### Host species — from the paper, else the vendor catalog

Species precedence, and the distinction that matters is **quotable source vs plausibility**:

| # | Source | Example |
|---|--------|---------|
| 1 | The paper states it | *"mouse anti-myc-tag antibody (Cell Signalling, 9B11)"* → `Mouse Anti-Myc` |
| 2 | **The vendor's catalog entry for the cited catalog number** | Bethyl `A300-864A` is a rabbit polyclonal → `Rabbit Anti-RBFOX2 (Bethyl A300-864A)` |
| 3 | Neither — **omit it** | `Anti-NOVA`, `Anti-RBFOX1` |

A catalog lookup is *not* a guess: the vendor record is a named source you can quote, which
is what §0 asks for. Inferring from plausibility is still forbidden — Nova is a POMA
autoantigen, which makes "human" tempting for E-MTAB-1008's anti-Nova, and with no vendor
there is nothing to check it against, so `Anti-NOVA` stays unqualified.

> **Reactivity is not host species.** Vendor pages advertise *species reactivity* far more
> prominently than host. Millipore `MAB377` both reacts with mouse and is raised in mouse, but
> Bethyl `A300-864A` reacts with human/mouse/rat and is raised in **rabbit** — reading the
> wrong field yields `Mouse Anti-RBFOX2`, which is wrong. Confirm the *host*.

### Allowed literals

| Value | When |
|-------|------|
| *(empty)* | **Size-matched input (SMInput), bead-only and IgG controls.** No antibody was used, and this database records that as an empty field rather than a literal string |
| `Strep/His affinity tag purification` | iCLAP (tag pulldown, not an antibody) |

> **Convention:** inputs carry an **empty** `purification_agent`. An earlier revision of this
> page prescribed the literal `no antibody`; that was reconciled to empty so IP rows are the
> only ones with a value, making "has an agent" a clean proxy for "is an IP". Applied across
> GSE290281 and GSE215250.

### Never

- **Never take the first antibody listed for the protein.** A Key Resources table that
  lists two anti-PARP13 antibodies is listing one for Western blot and one for the IP.
- **Never emit a vendor-less prose string.** `PARP13 antibody`, `anti-PARP13 antibody`,
  `V5-antibody`, `DHX9-mAb` are all rejected — they identify no reagent. (The bare canonical
  `Anti-PARP13` is a different thing and is allowed, with a warning, per above.)
- **Never invent a vendor to satisfy the format.** If the paper names no supplier, either the
  antibody is shared/in-house (use the bare form and put provenance in Comments) or the lookup
  is not finished. Guessing a plausible catalog number is the worst possible failure here: it
  is unverifiable, looks authoritative, and silently points at the wrong reagent.
- **Never infer the host species from plausibility.** Take it from the paper or the
  vendor's catalog entry, or omit it — and never from the antibody's *reactivity* list.
- **Never copy the IP antibody onto the input row.**

---

## 2. Cell or Tissue (`source`)

### Precedence

| # | Source | Example |
|---|--------|---------|
| 1 | Paper Key Resources cell line (with RRID/ATCC id) | `HEK 293T — ATCC CRL-3216` → `HEK293T` |
| 2 | GEO `cell line:` / `cell type:` characteristic | `cell type: HeLa` → `HeLa` |
| 3 | GEO `!Sample_source_name_ch1` | **last resort only** |

`resolve_source()` (`lib/flow_annotate.py`) implements 2 over 3. Step 1 stays an agent
responsibility — it needs the paper — and is exactly where HEK293 vs HEK293T is settled.

### Rejected values

| Value | Why |
|-------|-----|
| `ATCC Cell Lines` | Supplier phrase (GSE105082 `source_name_ch1`) — the real line is `HeLa` |
| `human embryonic kidney` | Generic descriptor (GSE215250) — the real line is `HEK293T` |
| `cell line`, `tissue`, `N/A`, `unknown` | Placeholders |
| *(empty)* | Now tracked in `ANNOTATION_WARNINGS.md` |

### `source__annotation` — the sub-field

`source` carries the **general** cell type or tissue (`HeLa`, `HEK293T`, `mESC`).
`source__annotation` carries **additional detail beyond it** — most often a specific
lineage, clone, or derivation name when the study uses a particular variant of a common
line. Flow displays the pair as `source:annotation`.

| `source` | `source__annotation` | When |
|----------|---------------------|------|
| `HeLa` | `Kyoto` | Study uses a named sub-line / lineage |
| `HEK293T` | *(empty)* | Plain parental line — nothing to add |
| `mESC` | `E14` | Named ESC line |
| `HeLa` | `Flp-In T-REx` | Engineered derivative background |

Leave it **empty** unless the paper names a specific lineage/clone — do not restate the
line itself, and do not put genotype or treatment here (those belong in `Condition`).

### Ambiguous pairs (warned, never auto-corrected)

`HEK293` ↔ `HEK293T` is the common trap: the parent and the SV40 large-T derivative are
different lines, and GEO frequently says the former when the paper says the latter. The
validator warns and **requires the researcher to confirm against the paper** — it never
rewrites, because guessing here silently corrupts the database.

---

## 3. Purification Target + Annotation (the tag)

### Target

Gene symbol, uppercase, from the GEO title or characteristics. Control libraries use their
own target — **never the IP's protein**:

| Library | `purification_target` | `purification_agent` |
|---------|----------------------|----------------------|
| eCLIP/seCLIP size-matched input | `SMInput` | *(empty)* |
| Bead-only / no-antibody control | `SMInput` | *(empty)* |
| IgG control | `IgG` | *(empty)* |
| **Antibody pulldown on cells lacking the target** | **`AbControl`** | **the antibody used** |
| GFP-only control construct | `GFP` | anti-GFP antibody |

**`AbControl` vs `SMInput`** — the distinction is whether an antibody was used. A
size-matched input has none, so its agent is empty. An `AbControl` is the *same*
immunoprecipitation performed on cells that do not express the tagged protein (GSE297587's
`U87 Control` rows are a myc IP on untransfected U87), so the antibody is real and must be
recorded. The validator enforces the opposite rules for the two: an `AbControl` with an
empty agent is an error, and its antibody naturally names the **tag** rather than the row's
target, so the agent/target agreement check is skipped.

The validator flags any row whose **name** contains `INPUT`/`SMINPUT` while its target is a
real protein — the single most common eCLIP annotation error.

Rejected targets: anything not gene-symbol shaped, plus antibody fragments (`ANTI-FLAG`) and
species names (`RABBIT`) that the title-parsing fallback can otherwise emit.

### Annotation grammar: `[<mutation>-]<terminus><tag>`

Flow renders `purification_target` and its annotation as **`TARGET:annotation`**, so the
annotation carries everything that describes *the protein that was purified*.

**Order is fixed: alteration first, tag last, hyphen-separated.**

| Rendered | Meaning |
|----------|---------|
| `LARP6:nMYC` | full-length LARP6, N-terminal myc tag |
| `LARP6:dNTR-nMYC` | LARP6 lacking the N-terminal region, N-terminal myc tag |
| `QKI:c3xFLAG-HBH` | full-length QKI, C-terminal 3xFLAG-HBH — **one composite tag**, not a mutation |
| `QKI:dNTR-c3xFLAG-HBH` | deletion mutant *and* composite tag |

Rules:

- **Record a protein alteration here when the construct is also tagged.** A deletion or
  point mutation is a property of the purified protein, so it belongs with the target — not
  only in `Condition`.
- **The unaltered construct takes no mutation prefix** — full-length is `nMYC`, not
  `FL-nMYC`.
- **A mutation alone is rejected.** An untagged mutant has no tag annotation; put the
  variant in `Condition` instead.
- **Reversed order is rejected** (`nMYC-dNTR`), because the tag must be identifiable as the
  trailing component.

Worked example — GSE297587 has five myc-LARP6 constructs plus a parental control:
`LARP6:nMYC`, `LARP6:dNTR-nMYC`, `LARP6:dNTD-nMYC`, `LARP6:dLaMod-nMYC`, `LARP6:dCTR-nMYC`,
and `AbControl` with no annotation.

### Tag vocabulary

**Terminal prefix + tag**, no separator: `c` = C-terminal, `n` = N-terminal.

| Value | Meaning |
|-------|---------|
| `c3xFLAG-HBH` | C-terminal 3xFLAG-HBH (uvCLAP / FLASHtagged platform) |
| `cV5` | C-terminal V5 (tethered eCLIP, anti-V5 pulldown) |
| `cGFP` / `nGFP` | GFP fusion, C- or N-terminal |
| `nFLAG`, `cHA`, `nMYC`, `cHBH` | Other single tags |
| *(empty)* | **Endogenous IP — no tag.** The correct value whenever the antibody targets the native protein |

Known tags: `3xFLAG-HBH`, `3xFLAG`, `FLAG`, `GFP`, `V5`, `HA`, `MYC`, `HBH`, `HIS`, `TAP`,
`SNAP`, `HALO`, `MS2`.

Rejected: `GFP` (no terminal prefix), `3xFLAG` (no prefix), `C-3xFLAG` (uppercase +
hyphen), `flag` (lowercase, no prefix).

### Terminus: read the construct name first, then default to C-terminal

| # | Evidence | Example |
|---|----------|---------|
| 1 | **Paper states the terminus** | "C-terminally V5-tagged" → `cV5` |
| 2 | **Construct name order** — tag before the gene is N-terminal, after it is C-terminal | `myc-LARP6` → `nMYC`; `LARP6-myc` → `cMYC` |
| 3 | **C-terminal default** (below) | no name, no statement → `cV5` |

Step 2 is the useful one in practice, because a construct name almost always appears in the
GEO sample titles even when the Methods never state a terminus. `terminus_from_construct_name()`
implements it against the title, the `expression vector:` characteristic and the protocol
text. GSE297587's titles (`Full-length mycLARP6-1`, …) resolve to **`nMYC`** this way.

### Terminal default: TAG-eCLIP is **C-terminal**

**When a tagged-RBP CLIP experiment does not state the terminus, assume C-terminal** — that
is the original TAG-eCLIP design, and the ORF libraries these screens draw on are cloned
without stop codons, which forces a C-terminal fusion. So the default tag string is
`cV5`, `c3xFLAG`, `cGFP` … and an N-terminal value (`nV5`) should only be written when the
paper says so.

The terminus is often unrecoverable from GEO and frequently absent from the paper too —
GSE290281's Methods say only *"V5-tagged eCLIP … following overexpression of each protein by
transfecting the protein expression plasmid as described previously"*, with no orientation
anywhere in the deposit, the supplementary manifest, or the abstract. Applying the
C-terminal default is what lets the field be filled at all.

### Tag the pulldown, not the cell line

**Only rows whose antibody is the anti-tag antibody carry the tag annotation.** In a study
that mixes tagged and endogenous pulldowns, every sample may come from tagged cells, but the
annotation describes *what was purified*:

| Row | Agent | `purification_target__annotation` |
|-----|-------|-----------------------------------|
| V5 pulldown of a tagged RBP | `… Anti-V5 (…)` | `cV5` |
| RBP-specific antibody, endogenous protein | `… Anti-RBM22 (…)` | **empty** |
| Size-matched input | *(empty)* | **empty** — target is `SMInput`, there is no construct to describe |

GSE290281 had `cV5` on RBM10 and RBM22, which were pulled down with their own antibodies
(`Anti-RBM10`, `Anti-RBM22`) — the tag was applied study-wide instead of per pulldown. Nine
rows were corrected: 8 cleared, 1 added.

### Where the annotation actually lives

Flow stores it **nested on the annotated field**, at
`metadata.purification_target.annotation` — *not* at a top-level
`metadata.purification_target__annotation` key. Write it with
`{"purification_target__annotation": "cV5"}` but **read it back from the nested location**,
or every row will look empty. Setting the value to `""` clears it.

### Deciding endogenous vs tagged

| Evidence | Conclusion |
|----------|------------|
| Methods say "anti-\<PROTEIN\> antibody" and no construct is transfected | Endogenous → annotation **empty** |
| GEO `expression vector:` names the gene + a tag, or `clip antibody:` is anti-FLAG/anti-V5/anti-GFP | Tagged → set the tag |
| `expression vector: HBH tag` / `empty vector` / `vector only` | Control construct → annotation **empty** |

**PARP13 (GSE215250) is endogenous** — anti-PARP13 pulls the native protein, so annotation
is empty on all four IP rows and all four SMInput rows.

---

## 3b. Experimental Method — ignore `library_strategy`

GEO's `!Sample_library_strategy` is chosen from a **fixed submission vocabulary** that has no
iCLIP/eCLIP entry, so submitters pick the nearest match. `RIP-Seq` on a CLIP study is the
normal outcome, not a discrepancy to investigate:

| Study | `library_strategy` | Actual method (from the protocol) |
|-------|--------------------|-----------------------------------|
| GSE76475 (Rbfox) | `RIP-Seq` | iCLIP — `data_processing` even says `library strategy: iCLIP-seq` |
| GSE113638 (AGO) | `RIP-Seq` | iCLIP, König 2011, UV 254 nm 150 mJ/cm² |
| GSE78030 (m6A readers) | `OTHER` | iCLIP, Huppertz 2014 |

**Take the method from the extraction protocol**, which names the published procedure and the
crosslinking chemistry, and treat `library_strategy` as uninformative. UV wavelength is the
useful discriminator in the protocol text: 254 nm is conventional CLIP/iCLIP, 365 nm with
4SU is PAR-CLIP.

---

## 3c. PubMed ID — a sample property, not a metadata attribute

`pubmed` does **not** appear in `flowbio samples batch-template --sample-type CLIP`, because
that lists metadata attributes only. It is nevertheless a real, editable field — it sits at
the **top level** of the sample, beside `name`:

```
POST /samples/{id}/edit  {"pubmed": "31216479"}     -> 200
GET  /samples/{id}                                   -> {"name": ..., "pubmed": "31216479", ...}
                                                        (NOT under "metadata")
```

Its absence from the template is why PMIDs were previously written into `comments`. That is
not merely untidy — **setting `pubmed` populates the owning project's `papers`** with a
resolved citation:

```json
"papers": [{"id": "31216479", "year": 2019, "journal": "Cell Rep",
            "title": "Genome-wide Integrative Analysis of Zika-Virus-Infected ..."}]
```

A project whose samples carry no PMID has `papers: []`. So a PMID left in `comments` loses
the paper linkage entirely, and the study becomes unfindable by publication.

**Always set it**, and remember it is verified from the top level — `live_value()` handles
that, but a hand-rolled check reading `metadata.pubmed` will always see nothing.

---

## 4. 5′ Barcode Sequence

Already gated by `CONFIRM_BARCODES.md`; two format rules belong here.

| Context | Value |
|---------|-------|
| Sample metadata (`five_prime_barcode_sequence`) | Literal `ACGTN` string — e.g. `NNNCAATNN`, `NNCCNNACC`. IUPAC codes (`R`, `Y`, `B`) normalize to `N` |
| Execution parameter (`umi_header_format`) | **Always all-`N`**, same length as the 5′ barcode — e.g. `NNNNNNNNN` for a 9 nt barcode |
| **eCLIP default** | `NNNNNNNNNN` (10 N) — the standard Van Nostrand / ENCODE randomer |

The whole 5′ barcode is used for deduplication, so the execution format is the *full*
length, not just the random positions.

---

## 5. Pre-upload checklist

Run through this before releasing the metadata gate.

| ✔ | Check |
|---|-------|
| ☐ | Every value traces to a quotable GEO field, SDRF column, or paper sentence |
| ☐ | Antibody came from the sentence naming the CLIP assay, not the first Key Resources row |
| ☐ | Antibody has species (if stated), target, vendor **and** catalog number |
| ☐ | Input / IgG rows have target `SMInput`/`IgG` and an **empty** purification agent |
| ☐ | Source is a specific line, not a supplier phrase or generic descriptor |
| ☐ | HEK293 vs HEK293T (and similar pairs) confirmed against the paper |
| ☐ | Tag annotation empty for endogenous IPs; correct `c`/`n` grammar when tagged |
| ☐ | 5′ barcode is `ACGTN`; `umi_header_format` is all-`N` of the same length |
| ☐ | Organism is `Hs`/`Mm`/`Gg`, never a scientific name |
| ☐ | Scientist = first author, PI = last author (from PubMed, not the GEO contact) |
| ☐ | `ANNOTATION_WARNINGS.md` reviewed; `CONFIRM_METADATA.md` has zero unresolved errors |

---

## 6. Worked example — GSE215250 (PARP13 eCLIP)

What a naive GEO-only scrape produces versus the correct answer:

| Field | Naive | Correct | Why |
|-------|-------|---------|-----|
| Purification Agent (IP) | *(empty)* or `Rabbit Anti-PARP13 (ProteinTech 16820-1-AP)` | `Anti-PARP13 (Thermo Fisher PA5-31650)` | ProteinTech antibody was used for **Western blot**; the eCLIP sentence names the Thermo one |
| Purification Agent (input) | copies the IP antibody | *(empty)* | Size-matched input |
| Cell or Tissue | `human embryonic kidney` | `HEK293T` | GEO descriptor; Key Resources gives ATCC CRL-3216 |
| Target (IP) | `PARP13` | `PARP13` | ✔ |
| Target (input) | `PARP13` | `SMInput` | Inputs never carry the IP protein |
| Target Annotation | `cGFP` guessed | *(empty)* | Endogenous IP, no construct |
| 5′ Barcode | *(empty)* | `NNNNNNNNNN` | eCLIP 10 nt randomer |

---

## 7. Judgement register — where the agent still decides

Fields the pipeline **cannot** derive deterministically. Each is a place two models can
produce different metadata for the same study, so each is a review target. Hardened items
are listed for contrast — they now fail loudly instead of silently.

### Hardened (validated or gated)

| Area | Was | Now |
|------|-----|-----|
| `purification_agent` | first Key Resources antibody; vendor-less strings passed | assay-sentence precedence; vendor **and** catalog required; dilutions (`1:500`) rejected as catalogs |
| `source` | `!Sample_source_name_ch1` first — supplier phrases reached Flow | `cell line:` / `cell type:` wins; supplier + generic descriptors rejected |
| `purification_target` | comma-lead returned any token — `HELA`, `RABBIT`, `ANTI-FLAG` | cell lines / host species / `ANTI-` rejected; **inputs → `SMInput`**, IgG → `IgG` |
| `experimental_method` | `"flash"` matched before `"iclip"`; *"flash-frozen"* rerouted whole studies | `flash-frozen` stripped, word boundaries, **series title outranks protocol prose** |
| Protocol detectors | bare substring over protocol blob | shared matcher; prose mentions no longer misfire |
| `--paper-text` | attaching an excerpt **disabled** the PMC Methods fetch | excerpt now **augments** the fetched Methods |
| Validation reach | warnings only when a PubMed ID existed | field checks run unconditionally; `CONFIRM_METADATA.md` blocks on errors |

### Still agent-decided — review these

| Risk | Area | Failure mode |
|------|------|--------------|
| **HIGH** | `srr_map.tsv` GSM↔SRR mapping | Agent-authored; nothing checks a run actually belongs to its GSM. A transposed row silently attaches the wrong reads to the wrong sample |
| **HIGH** | `_fastq_paths_for_gsm` multi-run GSMs | A single-end GSM with ≥2 runs pairs two **unrelated** SRRs as mates and drops runs 3+ |
| **HIGH** | Which `--paper-text` excerpt to attach | Now additive, but the excerpt still steers barcode extraction; two excerpt choices → two barcode proposals |
| MEDIUM | Replicate inference | `rep 3` / `replicate 3` / `batch 2` collapse to `Rep1`, which also mis-assigns per-replicate barcodes |
| MEDIUM | `Condition`, `Comments` | Never populated by code. GEO `treatment:` / `genotype:` are parsed then discarded, so ± treatment rows differ only by run id |
| MEDIUM | Barcode heuristic fallback | With no `--paper-text` / `--geo-cache-dir` / `--fetch-geo`, the confirmation gate is bypassed entirely and generic studies route to `resolve_flash` |
| MEDIUM | FLASH replicate barcodes | `NNRRNTTTTTTNN` / `NNYYNTTTTTTNN` are hardcoded from the literature but presented as ordinary proposals with `confidence: medium` |
| MEDIUM | `3' Barcode Sequence` | Not passed through `normalize_flow_barcode`, so IUPAC `R`/`Y` can reach Flow |
| MEDIUM | PubMed fetch failure | Falls back silently to the GEO contact name — non-empty, so no warning fires; run-to-run nondeterminism |
| LOW | Empty target | Becomes the literal token `unknown` in the Flow sample name |
| LOW | `Type` | Hardcoded `CLIP`; mixed series are mislabelled |

**Rule of thumb:** if a field is in the lower table, do not trust it from a single model
pass — check it against the paper before releasing the metadata gate.

---

## Organism is a code, not a name

`Organism` takes Flow's **two-letter code**. The Latin and common names that
`GET /api/organisms` returns alongside it are for display and are rejected on submission.

| Use | Not |
|---|---|
| `Hs` | `Homo sapiens`, `Human` |
| `Mm` | `Mus musculus`, `Mouse` |
| `Rn` `Dr` `Dm` `Sc` `Ec` `Gg` `At` `Vf` | their Latin or common names |

GSE159997's upload sheet carried `Mus musculus` and all 18 rows failed with
`{'organism': ['Does not exist.']}` — after 12.8 GB had been downloaded, rewritten and
staged. Nothing partial was created, but it is a long way to travel for a vocabulary error.

It is tempting to conclude that `samples import` and `samples upload` take different
vocabularies. **They do not** — every sheet that has ever worked, on either path, uses the
code. `validate_organism()` is case-sensitive because the API is; accepting `mm` would only
move the failure downstream.

---

## A stated barcode may be the RT primer, not the read

Papers often give the barcode as the **RT-primer sequence**. The read carries its **reverse
complement** — and reverse-complementing swaps the flanking random lengths:

```
primer   NN | XXXX | NNN          (2 random + 4 fixed + 3 random)
read     NNN | revcomp(XXXX) | NN (3 random + 4 fixed + 2 random)
```

GSE75418 (PMID 26694817) states `5'-phosphate-NNXXXXNNNAGATCGG…` with identifiers
`AACC, ACAC, AGGT, CGAC`. Entropy put the fixed bases at positions **4–7**, not 3–6, and the
observed barcodes were `GGTT, GTGT, ACCT, GTCG`. Reverse-complementing the paper's four
values reproduces the observed four **exactly, 4/4** — the paper is right, it is simply
describing the primer.

So a mismatch against a stated barcode has two candidate explanations, and they need
different responses:

| Observation | Meaning |
|---|---|
| revcomp matches, flanks swapped | the paper states the primer — record the **read** form |
| nothing matches under either orientation | the deposit is wrong (E-MTAB-2700) — trust the entropy |

Check the reverse complement before concluding a deposit is wrong.

## `noAbCtrl` is not `SMInput`

A **size-matched input** is material carried through the protocol. A **no-antibody control**
is an IP performed with beads and no antibody. Both take an empty `purification_agent`, and
they answer different questions — do not collapse them.

GSE75418's `noAbCtrl` yielded 595,480 reads against 14–40 M for its IPs, which the paper
reports as ~0.08% of the SAFB1 read count.
