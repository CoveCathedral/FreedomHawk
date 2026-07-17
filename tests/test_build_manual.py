"""The Markdown-to-HTML user-manual builder (scripts/build_manual.py)."""
import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location("build_manual", _ROOT / "scripts" / "build_manual.py")
bm = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bm)


@pytest.fixture(autouse=True)
def _reset_slugs():
    bm._slug_seen.clear()
    yield
    bm._slug_seen.clear()


def test_headings_get_anchors_and_toc():
    title, toc, body = bm.convert("# Title\n\n## First\n\ntext\n\n### Sub\n\nmore\n")
    assert title == "Title"
    assert (2, "first", "First") in toc
    assert (3, "sub", "Sub") in toc
    assert '<h2 id="first">First</h2>' in body
    assert "<h1>Title</h1>" in body


def test_duplicate_headings_get_unique_ids():
    _, toc, _ = bm.convert("## Setup\n\n## Setup\n")
    ids = [sid for _, sid, _ in toc]
    assert ids == ["setup", "setup-1"]     # no clashing anchors


def test_inline_bold_code_link_escaped():
    out = bm.inline("Press **Start**, run `x` then see [site](https://e.com)")
    assert "<strong>Start</strong>" in out
    assert "<code>x</code>" in out
    assert '<a href="https://e.com">site</a>' in out


def test_inline_escapes_html_but_not_code_markup():
    out = bm.inline("a < b & `c > d`")
    assert "&lt;" in out and "&amp;" in out
    assert "<code>c &gt; d</code>" in out   # code content escaped, wrapped in a real tag


def test_lists_and_tables_and_code_blocks():
    _, _, body = bm.convert(
        "- one\n- two\n\n```\ncode\n```\n\n| A | B |\n|---|---|\n| 1 | 2 |\n")
    assert "<ul><li>one</li><li>two</li></ul>" in body
    assert "<pre><code>code</code></pre>" in body
    assert "<table>" in body and "<th>A</th>" in body and "<td>1</td>" in body


def test_wrapped_list_item_joins_continuation():
    _, _, body = bm.convert("- first line\n  second line\n- next\n")
    assert "<li>first line second line</li>" in body


def test_full_manual_builds():
    src = _ROOT / "docs" / "user-manual.md"
    title, toc, body = bm.convert(src.read_text(encoding="utf-8"))
    assert title == "FreedomHawk User Manual"
    assert len(toc) >= 15
    page = bm.render_page(title, toc, body)
    assert "\x00" not in page                       # no leftover placeholders
    assert page.strip().startswith("<!doctype html>")
    assert 'id="content"' in page and 'class="toc"' in page
