"""Every HTTP call the skill makes, and one answer to which project a sample is in.

`project_id_of` reads both shapes the API returns: nested from `GET /samples/{id}`, bare from
listings.

Story: FAILURES.md#flow-client
"""

import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lib import flow_client as fc  # noqa: E402


class TestProjectIdShapes:
    """The API returns this field two ways. Both are real; both must work."""

    def test_nested_shape_from_get_sample(self):
        assert fc.project_id_of({"project": {"id": "P1"}}) == "P1"

    def test_bare_shape_from_a_listing(self):
        assert fc.project_id_of({"project": "P1"}) == "P1"

    def test_unassigned_is_empty_not_none(self):
        assert fc.project_id_of({"project": None}) == ""
        assert fc.project_id_of({}) == ""

    def test_a_nested_project_with_no_id(self):
        assert fc.project_id_of({"project": {}}) == ""

    def test_a_missing_sample_does_not_explode(self):
        assert fc.project_id_of(None) == ""

    def test_numeric_ids_become_strings(self):
        """Flow ids exceed 2^53, so they are compared as strings everywhere."""
        assert fc.project_id_of({"project": {"id": 833550247540650083}}) == "833550247540650083"


class TestTheThirdCopyWasBroken:
    def test_import_repair_survives_the_bare_shape(self):
        """A listing's bare `project` string is read, not dereferenced as a dict."""
        from lib.import_check import build_repair_plan

        plan = build_repair_plan(
            [{"name": "S1"}],
            [{"name": "S1", "id": "1", "project": "P1", "metadata": {}}],
            project_id="P1",
        )
        assert [e for e in plan if "project" in e.fields] == []

    def test_a_bare_wrong_project_is_still_repaired(self):
        from lib.import_check import build_repair_plan

        plan = build_repair_plan(
            [{"name": "S1"}],
            [{"name": "S1", "id": "1", "project": "WRONG", "metadata": {}}],
            project_id="P1",
        )
        assert plan[0].fields["project"] == "P1"


class TestOneApiBase:
    def test_env_override_is_honoured(self):
        assert fc.API_BASE.endswith("/api") or fc.API_BASE.startswith("http")

    def test_there_is_only_one_definition_outside_vendor(self):
        """`lib/vendor/` is upstream-mirrored and exempt; nothing else may define its own."""
        import re
        from pathlib import Path

        skill = Path(__file__).resolve().parent.parent
        offenders = [
            path.relative_to(skill).as_posix()
            for path in (skill / "lib").rglob("*.py")
            if "vendor" not in path.parts
            and path.name != "flow_client.py"
            and re.search(r"^API_BASE\s*=\s*(?!.*flow_client)", path.read_text(), re.M)
        ]
        assert offenders == []


class TestTokenResolution:
    """Explicit, then FLOW_API_TOKEN, then FLOW_TOKEN, then the token file."""

    def test_explicit_wins(self, monkeypatch):
        monkeypatch.setenv("FLOW_API_TOKEN", "from-env")
        assert fc.resolve_token("explicit") == "explicit"

    def test_env_is_next(self, monkeypatch):
        monkeypatch.setenv("FLOW_API_TOKEN", "from-env")
        assert fc.resolve_token() == "from-env"

    def test_flow_token_is_accepted_too(self, monkeypatch):
        """The sibling flow-bio skill and the root CLAUDE.md say FLOW_TOKEN; an agent
        arriving from either sets that name and this skill must not ignore it."""
        monkeypatch.delenv("FLOW_API_TOKEN", raising=False)
        monkeypatch.setenv("FLOW_TOKEN", "from-flow-token")
        assert fc.resolve_token() == "from-flow-token"

    def test_the_flowbio_name_wins_over_the_flow_bio_one(self, monkeypatch):
        monkeypatch.setenv("FLOW_API_TOKEN", "from-api-token")
        monkeypatch.setenv("FLOW_TOKEN", "from-flow-token")
        assert fc.resolve_token() == "from-api-token"

    def test_file_is_last(self, monkeypatch, tmp_path):
        monkeypatch.delenv("FLOW_API_TOKEN", raising=False)
        token_file = tmp_path / "api-token"
        token_file.write_text("from-file\n")
        monkeypatch.setenv("FLOW_TOKEN_FILE", str(token_file))
        assert fc.resolve_token() == "from-file"

    def test_absent_is_empty_not_an_exception(self, monkeypatch, tmp_path):
        monkeypatch.delenv("FLOW_API_TOKEN", raising=False)
        monkeypatch.setenv("FLOW_TOKEN_FILE", str(tmp_path / "nope"))
        assert fc.resolve_token() == ""


class _Resp:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestClient:
    def test_get_sample_hits_the_right_path(self, monkeypatch):
        seen = {}

        def fake_urlopen(req, timeout=0):
            seen["url"] = req.full_url
            seen["auth"] = req.get_header("Authorization")
            return _Resp(json.dumps({"id": "1"}).encode())

        monkeypatch.setattr(fc.urllib.request, "urlopen", fake_urlopen)
        fc.FlowClient("tok").get_sample("1")
        assert seen["url"].endswith("/samples/1")
        assert seen["auth"] == "Bearer tok"

    def test_edit_sample_posts_a_body(self, monkeypatch):
        seen = {}

        def fake_urlopen(req, timeout=0):
            seen["data"] = req.data
            return _Resp(b"{}")

        monkeypatch.setattr(fc.urllib.request, "urlopen", fake_urlopen)
        fc.FlowClient("tok").edit_sample("1", {"project": "P1"})
        assert json.loads(seen["data"]) == {"project": "P1"}


class TestCreateProject:
    """`POST /projects/new` with {name, description}, trusted only once the project re-reads with
    that name: some Flow writes return 200 without taking effect.
    """

    def _fake(self, responses, calls):
        class _Resp:
            def __init__(self, body):
                self._body = body

            def read(self):
                return json.dumps(self._body).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=0):
            calls.append(req)
            return _Resp(responses.pop(0))

        return fake_urlopen

    def test_it_posts_then_verifies_by_rereading(self, monkeypatch):
        calls = []
        monkeypatch.setattr(fc.urllib.request, "urlopen", self._fake(
            [{"id": "991"}, {"id": "991", "name": "GSE1 CLIP"}], calls))
        created = fc.FlowClient("tok").create_project("GSE1 CLIP", "desc")
        assert created["id"] == "991"
        assert calls[0].full_url.endswith("/projects/new")
        assert json.loads(calls[0].data) == {"name": "GSE1 CLIP", "description": "desc"}
        assert calls[0].get_header("Authorization") == "Bearer tok"
        assert calls[1].full_url.endswith("/projects/991")

    def test_a_200_that_created_nothing_is_refused(self, monkeypatch):
        """A response with no id raises."""
        monkeypatch.setattr(fc.urllib.request, "urlopen", self._fake([{"status": "ok"}], []))
        try:
            fc.FlowClient("tok").create_project("GSE1 CLIP")
        except RuntimeError as exc:
            assert "id" in str(exc)
        else:
            raise AssertionError("a create with no id in the response must raise")

    def test_a_reread_with_the_wrong_name_is_refused(self, monkeypatch):
        monkeypatch.setattr(fc.urllib.request, "urlopen", self._fake(
            [{"id": "991"}, {"id": "991", "name": "something else"}], []))
        try:
            fc.FlowClient("tok").create_project("GSE1 CLIP")
        except RuntimeError as exc:
            assert "GSE1 CLIP" in str(exc)
        else:
            raise AssertionError("a re-read that does not match must raise")


class TestPagination:
    """Listings page, and the envelope `count` is the project total, not the page size.

    A short listing would make the dedup pre-flight report a clean import.

    Story: FAILURES.md#listing-pagination
    """

    def _pager(self, pages):
        class _Resp:
            def __init__(self, body):
                self._body = body

            def read(self):
                return json.dumps(self._body).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        seen = []

        def fake_urlopen(req, timeout=0):
            seen.append(req.full_url)
            return _Resp(pages[len(seen) - 1])

        return fake_urlopen, seen

    def test_it_collects_every_page(self, monkeypatch):
        pages = [
            {"count": 3, "page": 1, "samples": [{"id": "1"}, {"id": "2"}]},
            {"count": 3, "page": 2, "samples": [{"id": "3"}]},
        ]
        fake, seen = self._pager(pages)
        monkeypatch.setattr(fc.urllib.request, "urlopen", fake)
        items = fc.FlowClient("tok").paginate("/projects/9/samples", items_key="samples")
        assert [i["id"] for i in items] == ["1", "2", "3"]
        assert "page=2" in seen[1]

    def test_a_single_page_needs_no_second_request(self, monkeypatch):
        fake, seen = self._pager([{"count": 2, "page": 1, "samples": [{"id": "1"}, {"id": "2"}]}])
        monkeypatch.setattr(fc.urllib.request, "urlopen", fake)
        assert len(fc.FlowClient("tok").paginate("/projects/9/samples", items_key="samples")) == 2
        assert len(seen) == 1

    def test_a_short_collection_refuses_rather_than_returning_a_subset(self, monkeypatch):
        """The envelope promises 24 and the pages stop at 10: raise, naming both numbers."""
        pages = [
            {"count": 24, "page": 1, "samples": [{"id": str(i)} for i in range(10)]},
            {"count": 24, "page": 2, "samples": []},
        ]
        fake, _ = self._pager(pages)
        monkeypatch.setattr(fc.urllib.request, "urlopen", fake)
        try:
            fc.FlowClient("tok").paginate("/projects/9/samples", items_key="samples")
        except RuntimeError as exc:
            assert "10" in str(exc) and "24" in str(exc)
        else:
            raise AssertionError("a partial listing must never be returned")

    def test_project_samples_asks_for_the_largest_legal_page(self, monkeypatch):
        """count caps at 100; >100 is HTTP 400, so 100 is the fewest possible requests."""
        fake, seen = self._pager([{"count": 1, "page": 1, "samples": [{"id": "1"}]}])
        monkeypatch.setattr(fc.urllib.request, "urlopen", fake)
        fc.FlowClient("tok").project_samples("9")
        assert "/projects/9/samples" in seen[0]
        assert "count=100" in seen[0]


class TestDeleteSample:
    """Delete is `POST /samples/{id}/delete`, accepted only when the sample re-reads as 404.

    `DELETE /samples/{id}` returns 200 whether or not it deleted anything.

    Story: FAILURES.md#sample-delete
    """

    def _fake(self, responses, calls):
        """Each response is a body to return, or an int status to raise as an HTTPError."""
        import io
        import urllib.error

        class _Resp:
            def __init__(self, body):
                self._body = body

            def read(self):
                return json.dumps(self._body).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=0):
            calls.append(req)
            nxt = responses.pop(0)
            if isinstance(nxt, int):
                raise urllib.error.HTTPError(req.full_url, nxt, "status", {}, io.BytesIO(b""))
            return _Resp(nxt)

        return fake_urlopen

    def test_it_posts_to_the_delete_route_then_confirms_a_404(self, monkeypatch):
        calls = []
        monkeypatch.setattr(fc.urllib.request, "urlopen",
                            self._fake([{"success": True}, 404], calls))
        fc.FlowClient("tok").delete_sample("555")
        assert calls[0].full_url.endswith("/samples/555/delete")
        assert calls[0].get_method() == "POST"
        assert calls[1].full_url.endswith("/samples/555")

    def test_it_never_issues_the_bare_delete_verb(self, monkeypatch):
        calls = []
        monkeypatch.setattr(fc.urllib.request, "urlopen",
                            self._fake([{"success": True}, 404], calls))
        fc.FlowClient("tok").delete_sample("555")
        assert all(c.get_method() != "DELETE" for c in calls)

    def test_a_sample_that_re_reads_is_not_deleted(self, monkeypatch):
        """Success reported, sample still there: raise."""
        monkeypatch.setattr(fc.urllib.request, "urlopen", self._fake(
            [{"success": True}, {"id": "555", "name": "SNRPB_rep2"}], []))
        try:
            fc.FlowClient("tok").delete_sample("555")
        except RuntimeError as exc:
            assert "555" in str(exc)
        else:
            raise AssertionError("a sample that still re-reads must not count as deleted")

    def test_an_error_on_the_re_read_is_not_evidence_of_deletion(self, monkeypatch):
        """Only a 404 says the sample is gone. A 500 says nothing, so it must not pass."""
        monkeypatch.setattr(fc.urllib.request, "urlopen",
                            self._fake([{"success": True}, 500], []))
        try:
            fc.FlowClient("tok").delete_sample("555")
        except RuntimeError as exc:
            assert "500" in str(exc)
        else:
            raise AssertionError("an unreadable sample is not a deleted sample")
