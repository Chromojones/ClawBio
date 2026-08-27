"""The docs make claims about the code. These check the claims that can be checked.

Two failures in this rebuild were documentation, not code. `SKILL.md` told a reader to write
`no antibody` for controls while the reference said empty and the validator warned on the
literal string; and "the import sheet has no `project` column" was stated in five places, true
when written and false after a library upgrade. Prose that contradicts the code is worse than
absent prose, because it is followed.

So: every `FAILURES.md` anchor a module cites must exist, every stage must appear in the stage
reference, and `SKILL.md` must stay inside the project's 500-line conformance rule.
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

    def test_the_four_gates_are_listed(self):
        text = STAGES_DOC.read_text()
        for stage in ("03_barcodes", "05_metadata", "108_params", "12_analysis"):
            assert stage in text
        assert text.count("GATE") >= 4

    def test_the_exit_codes_are_documented(self):
        """In BOTH files, each checked against `_common.py`.

        The exit-code table is the one thing deliberately stated twice: SKILL.md has to be
        readable on its own, and the codes are how you read the flowchart. Duplication is safe
        only while both copies are pinned to the source, which is what this does — change a
        code in `_common.py` and both documents fail here.
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
        """It once told the reader to write `no antibody`, which the validator warns about.

        The check is for the *instruction*, not the string. SKILL.md now cites that episode as
        the reason it stopped restating rules, and a plain grep cannot tell the warning from
        the thing it warns about — the third time this rebuild has written a test that matched
        its own documentation. So: any line mentioning the phrase must be marked historical.
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
        """Fifteen bullets of rules living in the wrong file is where the drift began."""
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
    """The project's 17-point SKILL.md checklist, run as a test instead of by hand.

    `/pr-audit` enforces this on every PR and the section names are matched exactly, so a
    lowercased heading fails an audit that a human reading the file would pass. Checking it
    here means the answer is known before the PR rather than after.
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
        """It advertised PubMed alert scanning after `pubmed_stage.py` was deleted."""
        fm = self._frontmatter().lower()
        assert "pubmed alert" not in fm
        assert "alert scan" not in fm
