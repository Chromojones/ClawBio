"""The docs make claims about the code; these check the ones that can be checked.

FAILURES.md anchors resolve, every stage is documented, and the flags, schemas, imports and
artefacts the docs name exist. SKILL.md meets the ClawBio conformance checklist.
"""

import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

FAILURES = SKILL_DIR / "FAILURES.md"
STAGES_DOC = SKILL_DIR / "reference" / "stages.md"
SKILL = SKILL_DIR / "SKILL.md"


def _cited_anchors():
    anchors = set()
    for path in [*SKILL_DIR.glob("lib/*.py"), *SKILL_DIR.glob("stages/*.py"),
                 *SKILL_DIR.glob("tests/**/*.py"), SKILL_DIR / "flow_compile.py"]:
        anchors |= set(re.findall(r"FAILURES\.md#([a-z0-9-]+)", path.read_text()))
    return anchors


def _reachable_literals() -> set[str]:
    """Every string literal in a stage, or in a lib function a stage reaches by name."""
    import ast

    defs = {}
    for path in SKILL_DIR.glob("lib/*.py"):
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                defs.setdefault(node.name, node)

    def names(node):
        found = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        found |= {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
        found |= {a.name for n in ast.walk(node) if isinstance(n, ast.ImportFrom) for a in n.names}
        return found

    def literals(node):
        return {n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)}

    stages = [ast.parse(p.read_text()) for p in SKILL_DIR.glob("stages/*.py")]
    text = set().union(*(literals(s) for s in stages))
    reach, frontier = set(), {n for s in stages for n in names(s) if n in defs}
    while frontier:
        name = frontier.pop()
        reach.add(name)
        text |= literals(defs[name])
        frontier |= {m for m in names(defs[name]) if m in defs and m not in reach}
    # a literal may carry a filename inside a longer string, e.g. an f-string part
    return {w for s in text for w in re.findall(r"[A-Za-z_0-9]+\.[a-z]+", s)} | text


class TestFailuresIndex:
    def test_it_exists(self):
        assert FAILURES.exists()

    def test_every_cited_anchor_resolves(self):
        """A docstring pointing at a missing anchor sends the reader nowhere."""
        defined = set(re.findall(r"^### ([a-z0-9-]+)$", FAILURES.read_text(), re.M))
        missing = sorted(_cited_anchors() - defined)
        assert missing == [], f"cited but not defined in FAILURES.md: {missing}"

    def test_every_anchor_points_at_a_test_file(self):
        """An incident with no test is a story, not a guardrail."""
        text = FAILURES.read_text()
        for block in text.split("\n### ")[1:]:
            name = block.split("\n", 1)[0]
            cited = re.findall(r"`(tests/[^`]+\.py)`", block)
            assert cited, f"{name} names no test"
            for rel in cited:
                assert (SKILL_DIR / rel).exists(), f"{name} names missing {rel}"


class TestStageReference:
    def test_every_stage_is_documented(self):
        stages = sorted(p.stem for p in (SKILL_DIR / "stages").glob("*.py")
                        if not p.name.startswith("_"))
        text = STAGES_DOC.read_text()
        missing = [s for s in stages if s not in text]
        assert missing == [], f"undocumented stages: {missing}"

    def test_the_gates_documented_are_the_gates_implemented(self):
        """Counted from the stages, so the doc cannot drift from the code."""
        gating = sorted(
            p.stem for p in (SKILL_DIR / "stages").glob("*.py")
            if not p.name.startswith("_") and "raise Gate(" in p.read_text()
        )
        assert gating == ["03_barcodes", "05_metadata", "108_params"], gating

        text = STAGES_DOC.read_text()
        for stage in gating:
            assert stage in text
        # Counting every "GATE" would count the table and the diagram twice over; what must
        # be true is that no fourth gate is claimed anywhere.
        assert "GATE 4" not in text
        for n in range(1, len(gating) + 1):
            assert f"GATE {n}" in text, f"GATE {n} missing"

    def test_the_exit_codes_are_documented(self):
        """In SKILL.md and reference/stages.md, each checked against `_common.py`.

        SKILL.md must read on its own, so the table is stated twice; both copies are pinned to the source.
        """
        from stages._common import CHECK_FAILED, GATE, OK, PREREQUISITE, USAGE

        for doc in (STAGES_DOC, SKILL):
            text = doc.read_text()
            for code in (OK, USAGE, GATE, CHECK_FAILED, PREREQUISITE):
                assert f"`{code}`" in text, f"exit code {code} undocumented in {doc.name}"


class TestSkillMd:
    def test_it_is_under_the_conformance_limit(self):
        """ClawBio's SKILL.md conformance checklist: under 500 lines."""
        n = len(SKILL.read_text().splitlines())
        assert n < 500, f"SKILL.md is {n} lines"

    def test_it_does_not_restate_field_rules(self):
        """SKILL.md does not instruct `no antibody`; a paragraph naming the phrase marks it historical.
        """
        for para in SKILL.read_text().split("\n\n"):
            if "no antibody" in para:
                flat = " ".join(para.split()).lower()
                assert "once told" in flat or "earlier revision" in flat, \
                    f"reads as current guidance: {flat[:120]}"

    def test_it_does_not_claim_the_sheet_lacks_a_project_column(self):
        text = SKILL.read_text().lower()
        assert "no `project` column" not in text
        assert "has no project field" not in text

    def test_it_points_at_the_references_rather_than_restating_them(self):
        """The map, not the rulebook. Each reference must be reachable from here."""
        text = SKILL.read_text()
        for ref in ("reference/stages.md", "reference/metadata-accuracy-checklist.md",
                    "reference/eclip-analysis-params.md", "FAILURES.md"):
            assert ref in text, f"SKILL.md does not link {ref}"

    def test_the_gotchas_section_stays_empty(self):
        """Field rules live in the references, not in SKILL.md gotchas."""
        text = SKILL.read_text()
        body = text.split("## Gotchas", 1)[1].split("##", 1)[0]
        assert "- " not in body, "rules are accumulating in SKILL.md again"


class TestNoDanglingLinks:
    """A pointer to a deleted file is worse than no pointer: it reads as an authority."""

    def test_every_local_markdown_link_resolves(self):
        import re

        bad = []
        for doc in [SKILL_DIR / "SKILL.md", SKILL_DIR / "FAILURES.md",
                    *SKILL_DIR.glob("reference/*.md"), *SKILL_DIR.glob("*.md")]:
            for target in re.findall(r"\]\(([^)#][^)]*)\)", doc.read_text()):
                if target.startswith(("http", "mailto")):
                    continue
                if not (SKILL_DIR / target.split("#")[0]).exists():
                    bad.append(f"{doc.name} -> {target}")
        assert bad == [], f"dangling links: {bad}"

    def test_the_folded_docs_are_gone(self):
        assert not (SKILL_DIR / "WORKFLOW.md").exists()
        assert not (SKILL_DIR / "DESIGN.md").exists()

    def test_nothing_still_points_at_them(self):
        """`reference/barcode-examples.md` may say DESIGN.md was folded in; it must not link it."""
        import re

        for doc in [*SKILL_DIR.glob("*.md"), *SKILL_DIR.glob("reference/*.md")]:
            for target in re.findall(r"\]\(([^)]*)\)", doc.read_text()):
                assert "WORKFLOW.md" not in target, doc.name
                assert "DESIGN.md" not in target, doc.name


class TestClawBioConformance:
    """The project's 17-point SKILL.md checklist, as a test.

    `/pr-audit` matches section names exactly, so casing matters.
    """

    def _frontmatter(self):
        return SKILL.read_text().split("---", 2)[1]

    def test_name_matches_the_folder(self):
        assert f"name: {SKILL_DIR.name}" in self._frontmatter()

    def test_version_is_semver(self):
        import re

        assert re.search(r"version: \d+\.\d+\.\d+", self._frontmatter())

    def test_the_required_frontmatter_keys_are_present(self):
        fm = self._frontmatter()
        for key in ("author:", "description:", "inputs:", "outputs:", "trigger_keywords:"):
            assert key in fm, key

    def test_at_least_three_trigger_keywords(self):
        import re

        block = self._frontmatter().split("trigger_keywords:")[1]
        assert len(re.findall(r"^      - .+$", block, re.M)) >= 3

    def test_the_required_sections_exist_with_the_template_casing(self):
        """Title case, as `templates/SKILL-TEMPLATE.md` defines them."""
        text = SKILL.read_text()
        for heading in ("## Trigger", "## Scope", "## Workflow", "## Example Output",
                        "## Safety", "## Agent Boundary"):
            assert f"\n{heading}\n" in text, heading

    def test_the_trigger_has_both_lists(self):
        text = SKILL.read_text()
        assert "Fire when" in text and "Do **not** fire" in text

    def test_the_disclaimer_is_present(self):
        assert "not a medical device" in SKILL.read_text()

    def test_demo_data_and_tests_exist(self):
        assert (SKILL_DIR / "demo").is_dir()
        assert list((SKILL_DIR / "tests").rglob("test_*.py"))

    def test_the_description_does_not_promise_what_was_removed(self):
        """The description advertises only what the skill does."""
        fm = self._frontmatter().lower()
        assert "pubmed alert" not in fm
        assert "alert scan" not in fm


class TestGateCountProse:
    """The gate count in SKILL.md prose matches the code: three."""

    def test_the_prose_never_claims_a_fourth_gate(self):
        text = SKILL.read_text().lower()
        for phrase in ("four gates", "four points", "four hard stops"):
            assert phrase not in text, f"SKILL.md still says {phrase!r}; the code has three"

    def test_the_prose_count_matches_the_code(self):
        gating = [p for p in (SKILL_DIR / "stages").glob("*.py")
                  if not p.name.startswith("_") and "raise Gate(" in p.read_text()]
        words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}
        assert f"{words[len(gating)]} hard stops" in SKILL.read_text().lower()


class TestDemoMd:
    """Every flag a DEMO.md bash block passes to a script in this skill exists in that script.
    """

    def _commands(self):
        """(script_path, [flags]) for each command line in a fenced bash block."""
        text = (SKILL_DIR / "DEMO.md").read_text()
        found = []
        for block in re.findall(r"```(?:bash|sh)\n(.*?)```", text, re.S):
            joined = block.replace("\\\n", " ")
            for line in joined.splitlines():
                match = re.search(r"(\S*(?:flow_compile|stages/[0-9]+_\w+)\.py)", line)
                if not match:
                    continue
                script = SKILL_DIR / Path(match.group(1)).name if "stages/" not in match.group(1) \
                    else SKILL_DIR / "stages" / Path(match.group(1)).name
                flags = [f.split("=")[0] for f in re.findall(r"--[a-z][a-z0-9-]*", line)]
                found.append((script, flags))
        return found

    def test_it_shows_at_least_one_stage_command(self):
        """A demo that never runs a stage is not a demo of this skill."""
        assert self._commands(), "no flow_compile.py or stages/*.py commands in DEMO.md"

    def test_every_script_it_names_exists(self):
        for script, _ in self._commands():
            assert script.exists(), f"DEMO.md names missing script {script.name}"

    def test_every_flag_it_shows_exists_in_the_script(self):
        bad = []
        for script, flags in self._commands():
            if not script.exists():
                continue
            source = script.read_text()
            if "_common" in source and "parser_for" in source:
                source += (SKILL_DIR / "stages" / "_common.py").read_text()  # shared flags
            for flag in flags:
                if f'"{flag}"' not in source and f"'{flag}'" not in source:
                    bad.append(f"{script.name} {flag}")
        assert bad == [], f"DEMO.md shows flags the scripts do not take: {bad}"


class TestDocumentedSchemasLoad:
    """Every documented `srr_map.tsv` column list loads in the real loader.

    Story: FAILURES.md#srr-map-schema
    """

    def _documented_schemas(self):
        """(doc, [columns]) for each line describing srr_map.tsv with a backticked list."""
        found = []
        for doc in [SKILL, *SKILL_DIR.glob("reference/*.md"), SKILL_DIR / "DEMO.md"]:
            for line in doc.read_text().splitlines():
                if "srr_map.tsv" not in line:
                    continue
                columns = [c for c in re.findall(r"`([a-z0-9_]+)`", line)
                           if c not in {"srr_map", "tsv"}]
                if len(columns) >= 2:
                    found.append((doc.name, columns))
        return found

    def test_a_schema_is_actually_documented(self):
        assert self._documented_schemas(), "no srr_map.tsv column list found in the docs"

    def test_every_documented_schema_loads(self, tmp_path):
        from lib.flow_annotate import load_srr_map

        values = {"gsm": "GSM1", "srr": "SRR1", "srx": "SRX1", "mate": "1",
                  "fastq": "SRR1.fastq.gz"}
        for doc, columns in self._documented_schemas():
            path = tmp_path / f"{doc}_srr_map.tsv"
            path.write_text("\t".join(columns) + "\n"
                            + "\t".join(values.get(c, "x") for c in columns) + "\n")
            try:
                load_srr_map(path)
            except ValueError as exc:
                raise AssertionError(
                    f"{doc} documents srr_map.tsv as {columns}, which the loader "
                    f"refuses: {exc}"
                ) from None


class TestTheGeoFetchRecipeMatchesTheCode:
    """The documented GEO recipe is `geo_url()`: the `form=text` SOFT endpoint, since the default
    accession page is behind reCAPTCHA.
    """

    def test_the_documented_url_is_the_one_the_code_builds(self):
        from lib.study_check import geo_url

        built = geo_url("GSE262435")
        text = (SKILL_DIR / "reference" / "sra-direct-import.md").read_text()
        for fragment in ("form=text", "targ=self"):
            assert fragment in built
            assert fragment in text, f"{fragment} is in geo_url() but undocumented"

    def test_the_recaptcha_trap_is_named(self):
        text = (SKILL_DIR / "reference" / "sra-direct-import.md").read_text().lower()
        assert "recaptcha" in text or "captcha" in text


class TestReferenceDocsNameRealThings:
    """Reference docs name only flags that exist and artefacts a run writes."""

    #: Flags belonging to tools this skill drives rather than defines.
    _EXTERNAL_FLAGS = {
        "--reads1", "--reads2", "--project", "--job-id", "--token-file", "--username",
        "--password", "--seq-defline", "--origfmt", "--split-files", "--stdout",
        "--concatenate-reads", "--align", "--twopass", "--length", "--out", "--sheet",
        "--params-json", "--filter", "--pid", "--yes", "--dry-run", "--execute-upload",
        "--sample-type", "--profile", "--input", "--outdir",
    }

    def _docs(self):
        return [*SKILL_DIR.glob("reference/*.md"), SKILL_DIR / "SKILL.md"]

    def _code(self):
        parts = [p.read_text() for p in SKILL_DIR.glob("stages/*.py")]
        parts += [p.read_text() for p in SKILL_DIR.glob("lib/*.py")]
        parts += [p.read_text() for p in SKILL_DIR.glob("lib/vendor/**/*.py")]
        parts.append((SKILL_DIR / "flow_compile.py").read_text())
        return "\n".join(parts)

    def test_every_flag_named_exists_somewhere_in_the_code(self):
        code = self._code()
        bad = []
        for doc in self._docs():
            for flag in sorted(set(re.findall(r"(?<![\w-])--[a-z][a-z0-9-]{2,}", doc.read_text()))):
                if flag in self._EXTERNAL_FLAGS:
                    continue
                if f'"{flag}"' not in code and f"'{flag}'" not in code:
                    bad.append(f"{doc.name}: {flag}")
        assert bad == [], f"docs name flags the code does not define: {bad}"

    def test_every_artefact_named_is_one_a_stage_writes(self):
        """A filename counts only if a stage, or lib code a stage reaches, names it.

        A writer no stage calls produces nothing in a run.
        """
        written = _reachable_literals()
        external = {"srr_map.tsv", "samplesheet.csv", "Testtemplate.xlsx", "edits.csv"}
        bad = []
        for doc in self._docs():
            for name in sorted(set(re.findall(
                    r"`([A-Za-z_0-9]+\.(?:json|md|csv|tsv|sh|txt))`", doc.read_text()))):
                if name in external or name.startswith(("demo", "paper_", "geo_", "params_")):  # agent-authored
                    continue
                if name in ("SKILL.md", "DEMO.md", "FAILURES.md", "README.md"):
                    continue
                if name not in written:
                    bad.append(f"{doc.name}: {name}")
        assert bad == [], f"docs name artefacts no stage writes: {bad}"



class TestDocImportsResolve:
    """Every `from lib.x import a, b` a doc shows must name a real module and real names."""

    def test_every_documented_import_resolves(self):
        import ast

        bad = []
        docs = [*SKILL_DIR.glob("reference/*.md"), SKILL_DIR / "SKILL.md", SKILL_DIR / "DEMO.md"]
        for doc in docs:
            for module, imported in re.findall(r"from (lib(?:\.[a-z_]+)+) import ([A-Za-z_, ]+)", doc.read_text()):
                path = SKILL_DIR / (module.replace(".", "/") + ".py")
                if not path.exists():
                    bad.append(f"{doc.name}: {module} (no such module)")
                    continue
                tree = ast.parse(path.read_text())
                defined = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
                defined |= {t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets
                            if isinstance(t, ast.Name)}
                defined |= {n.target.id for n in tree.body if isinstance(n, ast.AnnAssign)
                            and isinstance(n.target, ast.Name)}
                defined |= {a.asname or a.name for n in tree.body if isinstance(n, ast.ImportFrom)
                            for a in n.names}
                for name in (x.strip() for x in imported.split(",")):
                    if name and name not in defined:
                        bad.append(f"{doc.name}: {module}.{name}")
        assert bad == [], f"docs import things that do not exist: {bad}"
