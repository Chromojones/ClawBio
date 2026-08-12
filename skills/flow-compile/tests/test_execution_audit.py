"""Post-execution audit: an execution can finish "successfully" with samples missing.

GSE78030 execution 261164407803419211 launched seven ~10 GB CAT_FASTQ merges at once. Two
were SIGKILLed (exit 137) and the Nextflow log said:

    NOTE: Process CAT_FASTQ (YTHDF1...) terminated with an error exit status (137)
          -- Error is ignored

`errorStrategy = ignore` means the pipeline carries on. YTHDF1 and YTHDC1 got no downstream
stages at all, so the run was heading for a green finish having analysed 5 of 7 samples.

The check compares each sample against the run's own deepest sample rather than against a
named terminal stage. A first attempt hardcoded MULTIQC and flagged *every* finished run,
because MULTIQC is a run-level aggregate with no sample attached — so no sample ever
"reaches" it. Comparing samples to each other needs no pipeline knowledge and cannot make
that mistake.
"""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib.execution_audit import find_dropped_samples  # noqa: E402

FULL = ["CAT_FASTQ", "UMITOOLS_EXTRACT", "TRIMGALORE", "BOWTIE_ALIGN", "ICOUNT_SIGXLS"]


def run(spec, run_level=("MULTIQC", "CLIPSEQ_CLIPQC")):
    """spec: {sample: [(stage, status), ...]} plus run-level rows with no sample."""
    out = []
    for sample, stages in spec.items():
        for stage, status in stages:
            out.append({"sample": {"name": sample}, "process_name": f"CLIPSEQ:X:{stage}",
                        "status": status})
    out += [{"process_name": f"CLIPSEQ:{s}", "status": "COMPLETED"} for s in run_level]
    return out


class TestFindDroppedSamples:
    def test_a_uniform_finished_run_reports_nothing(self):
        """The false-positive regression: every sample equal must be silent."""
        spec = {s: [(x, "COMPLETED") for x in FULL] for s in ("A", "B", "C")}
        assert find_dropped_samples(run(spec)) == []

    def test_run_level_processes_do_not_make_samples_look_incomplete(self):
        """MULTIQC has no sample; it must not count as a stage any sample failed to reach."""
        spec = {s: [(x, "COMPLETED") for x in FULL] for s in ("A", "B")}
        assert find_dropped_samples(run(spec, run_level=("MULTIQC",))) == []

    def test_sample_whose_merge_failed_is_reported(self):
        spec = {"YTHDF1": [("CAT_FASTQ", "FAILED")],
                "YTHDF2": [(x, "COMPLETED") for x in FULL]}
        dropped = find_dropped_samples(run(spec))
        assert [d.sample_name for d in dropped] == ["YTHDF1"]
        assert "CAT_FASTQ" in dropped[0].reason

    def test_sample_that_silently_stops_is_reported(self):
        """No FAILED row anywhere — the sample just stops short of the others."""
        spec = {"YTHDC1": [(x, "COMPLETED") for x in FULL[:2]],
                "YTHDF2": [(x, "COMPLETED") for x in FULL],
                "YTHDF3": [(x, "COMPLETED") for x in FULL]}
        dropped = find_dropped_samples(run(spec))
        assert [d.sample_name for d in dropped] == ["YTHDC1"]
        assert "2" in dropped[0].reason and "5" in dropped[0].reason

    def test_still_running_samples_are_not_called_dropped(self):
        spec = {"A": [(x, "COMPLETED") for x in FULL],
                "B": [("CAT_FASTQ", "COMPLETED"), ("UMITOOLS_EXTRACT", "-")]}
        assert find_dropped_samples(run(spec), finished=False) == []

    def test_a_hard_failure_is_reported_even_mid_run(self):
        spec = {"A": [(x, "COMPLETED") for x in FULL], "B": [("CAT_FASTQ", "FAILED")]}
        dropped = find_dropped_samples(run(spec), finished=False)
        assert [d.sample_name for d in dropped] == ["B"]

    def test_exit_137_is_named_as_a_kill(self):
        spec = {"A": [("CAT_FASTQ", "FAILED")], "B": [(x, "COMPLETED") for x in FULL]}
        dropped = find_dropped_samples(run(spec), log="exit status (137)")
        assert "137" in dropped[0].reason and "kill" in dropped[0].reason.lower()

    def test_single_sample_run_has_no_peer_to_compare_against(self):
        """One sample cannot be 'behind' anyone — only a real failure counts."""
        assert find_dropped_samples(run({"A": [("CAT_FASTQ", "COMPLETED")]})) == []

    def test_empty_execution_is_safe(self):
        assert find_dropped_samples([]) == []
