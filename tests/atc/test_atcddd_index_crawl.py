"""Tests for the reproducible all-level WHOCC ATC/DDD Index crawler."""

from __future__ import annotations

from io import BytesIO

from ocl_pipeline_loader import load


crawler = load("who/atc", "atcddd_index")
cli = load("who/atc", "cli")


ROOT_HTML = """
<html><body>
<a href="./?code=A&amp;showdescription=no">ALIMENTARY TRACT AND METABOLISM</a>
</body></html>
"""

LEVEL_1_HTML = """
<html><body>
<a href="./?code=A&amp;showdescription=no">ALIMENTARY TRACT AND METABOLISM</a>
<a href="./?code=A01&amp;showdescription=no">STOMATOLOGICAL PREPARATIONS</a>
</body></html>
"""

LEVEL_2_HTML = """
<html><body>
<a href="./?code=A01&amp;showdescription=no">STOMATOLOGICAL PREPARATIONS</a>
<a href="./?code=A01A&amp;showdescription=no">STOMATOLOGICAL PREPARATIONS</a>
</body></html>
"""

LEVEL_3_HTML = """
<html><body>
<a href="./?code=A01A&amp;showdescription=no">STOMATOLOGICAL PREPARATIONS</a>
<a href="./?code=A01AD&amp;showdescription=no">Other agents for local oral treatment</a>
</body></html>
"""

LEVEL_4_HTML = """
<html><body>
<a href="./?code=A01AD&amp;showdescription=no">Other agents for local oral treatment</a>
<table><tr><td>ATC code</td><td>Name</td></tr>
<tr><td>A01AD02&nbsp;</td><td><a href="./?code=A01AD02&amp;showdescription=yes">benzydamine</a></td></tr>
<tr><td>A01AD11&nbsp;<sup>7)</sup></td><td><a href="./?code=A01AD11&amp;showdescription=yes">various</a></td></tr>
</table>
</body></html>
"""


class _Response(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()


def _opener(url, timeout):
    html_by_code = {
        None: ROOT_HTML,
        "A": LEVEL_1_HTML,
        "A01": LEVEL_2_HTML,
        "A01A": LEVEL_3_HTML,
        "A01AD": LEVEL_4_HTML,
    }
    code = crawler.code_from_url(url)
    return _Response(html_by_code[code].encode("utf-8"))


def test_crawl_collects_every_atc_level_and_uses_table_rows_for_leaves():
    result = crawler.crawl(opener=_opener, sleeper=lambda seconds: None)

    assert [(record.code, record.level, record.title, record.parent) for record in result.records] == [
        ("A", 1, "ALIMENTARY TRACT AND METABOLISM", None),
        ("A01", 2, "STOMATOLOGICAL PREPARATIONS", "A"),
        ("A01A", 3, "STOMATOLOGICAL PREPARATIONS", "A01"),
        ("A01AD", 4, "Other agents for local oral treatment", "A01A"),
        ("A01AD02", 5, "benzydamine", "A01AD"),
        ("A01AD11", 5, "various", "A01AD"),
    ]
    assert result.pages_requested == 5
    assert result.errors == []
    assert result.counts_by_level == {1: 1, 2: 1, 3: 1, 4: 1, 5: 2}


def test_crawl_refuses_a_malformed_child_code():
    html = "<a href='./?code=A01AD02&amp;showdescription=no'>not a direct child</a>"

    try:
        crawler.parse_nonleaf_children(html, parent_code="A01")
    except ValueError as error:
        assert "unexpected" in str(error)
    else:
        raise AssertionError("expected malformed direct child code to be rejected")


def test_leaf_table_ignores_its_level_4_self_row():
    html = """
    <table><tr><td>ATC code</td><td>Name</td></tr>
    <tr><td>A01AD</td><td>Other agents for local oral treatment</td></tr>
    <tr><td>A01AD02</td><td>benzydamine</td></tr></table>
    """
    assert crawler.parse_leaf_rows(html, "A01AD") == [("A01AD02", "benzydamine")]


def test_cli_writes_reproducible_snapshot_json_and_html(tmp_path, ttl_path, monkeypatch):
    result = crawler.CrawlResult(
        records=[crawler.IndexRecord("A", "ALIMENTARY TRACT AND METABOLISM", 1, None)],
        pages_requested=1,
        errors=[],
        last_updated="2099-01-20",
    )
    monkeypatch.setattr(cli.atcddd_index, "crawl", lambda **kwargs: result)

    output_dir = tmp_path / "audit"
    assert cli.main(["crawl-index", "--ttl", str(ttl_path), "--output-dir", str(output_dir), "--delay-seconds", "0"]) == 0
    payload = __import__("json").loads((output_dir / "whoatc_index_snapshot.json").read_text(encoding="utf-8"))
    assert payload["metadata"]["crawl_scope"].startswith("all ATC levels 1-5")
    assert payload["counts"]["total"] == 1
    assert (output_dir / "whoatc_bioportal_vs_who_audit.json").is_file()
    assert (output_dir / "whoatc_bioportal_vs_who_audit.html").is_file()
