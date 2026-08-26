"""One place that talks to the network, and one answer to "which project is this sample in?".

Every HTTP call in the skill lived where it was first needed. `_http_get` was written twice
(`sra_header_preview` with Range support, `paper_metadata_enrich` with HTTPError wrapping —
neither had the other's feature). `API_BASE` was defined twice outside `lib/vendor/`.
`RestFlowApi` knew two endpoints and lived inside a module about project assignment.

The sharper problem is `project_id_of`, which existed **three** times because the Flow API
returns the field in two shapes: nested (`{"project": {"id": "P1"}}`) from `GET /samples/{id}`,
and bare (`{"project": "P1"}`) from listings. Two of the three handle both. The third —
`import_repair.py:101`, `(sample.get("project") or {}).get("id") or ""` — raises AttributeError
on the bare shape, so the repair stage crashes on exactly the listing payload it exists to
repair.

`download_url` is here because the route is not guessable and was found by trial: it sits under
`/api/` (unlike the app-level URLs) and takes a **Data** id despite the `downloads` prefix.

Story: FAILURES.md#flow-client
"""

import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
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
        """`(sample.get("project") or {}).get("id")` raised AttributeError on a bare string.

        The repair stage runs against listing payloads, which is the shape it could not read.
        """
        from lib.import_repair import build_repair_plan

        plan = build_repair_plan(
            [{"name": "S1"}],
            [{"name": "S1", "id": "1", "project": "P1", "metadata": {}}],
            project_id="P1",
        )
        assert [e for e in plan if "project" in e.fields] == []

    def test_a_bare_wrong_project_is_still_repaired(self):
        from lib.import_repair import build_repair_plan

        plan = build_repair_plan(
            [{"name": "S1"}],
            [{"name": "S1", "id": "1", "project": "WRONG", "metadata": {}}],
            project_id="P1",
        )
        assert plan[0].fields["project"] == "P1"


class TestOneApiBase:
    def test_env_override_is_honoured(self):
        assert fc.API_BASE.endswith("/api") or fc.API_BASE.startswith("http")

    def test_credentials_and_client_agree(self):
        from lib import credentials

        assert credentials.API_BASE == fc.API_BASE

    def test_flow_project_assign_agrees(self):
        from lib import flow_project_assign

        assert flow_project_assign.API_BASE == fc.API_BASE


class TestDownloadRoute:
    """Found by trial. Not guessable, so it is pinned."""

    def test_the_route_sits_under_api(self):
        url = fc.download_url("391774392749683306", "SRR123_1.fastq.gz")
        assert "/api/downloads/391774392749683306/SRR123_1.fastq.gz" in url

    def test_the_filename_is_url_quoted(self):
        assert "%20" in fc.download_url("1", "a b.fastq.gz")

    def test_a_slash_in_the_filename_cannot_escape_the_route(self):
        assert fc.download_url("1", "../../etc/passwd").endswith("%2F..%2Fetc%2Fpasswd")


class TestHttpGet:
    """Both features from both original copies, in one function."""

    def test_range_header_is_sent_when_asked(self, monkeypatch):
        seen = {}

        def fake_urlopen(req, timeout=0):
            seen["range"] = req.get_header("Range")
            return _Resp(b"data")

        monkeypatch.setattr(fc.urllib.request, "urlopen", fake_urlopen)
        fc.http_get("https://example.invalid/x", byte_range=1024)
        assert seen["range"] == "bytes=0-1024"

    def test_no_range_header_by_default(self, monkeypatch):
        seen = {}

        def fake_urlopen(req, timeout=0):
            seen["range"] = req.get_header("Range")
            return _Resp(b"data")

        monkeypatch.setattr(fc.urllib.request, "urlopen", fake_urlopen)
        fc.http_get("https://example.invalid/x")
        assert seen["range"] is None

    def test_user_agent_identifies_the_skill(self, monkeypatch):
        seen = {}

        def fake_urlopen(req, timeout=0):
            seen["ua"] = req.get_header("User-agent")
            return _Resp(b"")

        monkeypatch.setattr(fc.urllib.request, "urlopen", fake_urlopen)
        fc.http_get("https://example.invalid/x")
        assert "flow-compile" in seen["ua"]

    def test_an_http_error_names_the_url(self, monkeypatch):
        import urllib.error

        def fake_urlopen(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

        monkeypatch.setattr(fc.urllib.request, "urlopen", fake_urlopen)
        try:
            fc.http_get("https://example.invalid/missing")
        except RuntimeError as exc:
            assert "404" in str(exc) and "example.invalid" in str(exc)
            return
        raise AssertionError("expected RuntimeError")


class TestTokenResolution:
    """FLOW_API_TOKEN → explicit → file, matching the flowbio CLI."""

    def test_explicit_wins(self, monkeypatch):
        monkeypatch.setenv("FLOW_API_TOKEN", "from-env")
        assert fc.resolve_token("explicit") == "explicit"

    def test_env_is_next(self, monkeypatch):
        monkeypatch.setenv("FLOW_API_TOKEN", "from-env")
        assert fc.resolve_token() == "from-env"

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
