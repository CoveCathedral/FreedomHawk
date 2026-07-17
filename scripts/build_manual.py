"""Build a navigable HTML user manual from ``docs/user-manual.md``.

Standard library only (no markdown dependency).  Produces a single self-contained,
high-contrast, large-text HTML page with an auto-generated table of contents and
anchored headings, so it navigates well both visually and with a screen reader
(NVDA browse mode jumps by heading; the TOC links jump for low-vision users).

Run:  python scripts/build_manual.py
It reads docs/user-manual.md and writes docs/user-manual.html.
"""
from __future__ import annotations

import html
import re
import sys
from pathlib import Path

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_LIST_ITEM = re.compile(r"^(\s*)([-*]|\d+\.)\s+(.*)$")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_CODE = re.compile(r"`([^`]+)`")

_slug_seen: dict[str, int] = {}


def slugify(text: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "section"
    n = _slug_seen.get(base, 0)
    _slug_seen[base] = n + 1
    return base if n == 0 else f"{base}-{n}"


def inline(text: str) -> str:
    """Inline markup: code spans, links, bold — HTML-escaped and injection-safe."""
    codes: list[str] = []

    def stash(m: re.Match) -> str:
        codes.append(html.escape(m.group(1), quote=False))
        return f"\x00{len(codes) - 1}\x00"

    text = _CODE.sub(stash, text)                       # protect code from later markup
    text = html.escape(text, quote=False)
    text = _LINK.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    for i, code in enumerate(codes):
        text = text.replace(f"\x00{i}\x00", f"<code>{code}</code>")
    return text


def _render_list(items: list[tuple[str, list[str]]], ordered: bool) -> str:
    tag = "ol" if ordered else "ul"
    lis = "".join(f"<li>{inline(' '.join(parts).strip())}</li>" for _, parts in items)
    return f"<{tag}>{lis}</{tag}>"


def _render_table(rows: list[list[str]]) -> str:
    head = rows[0]
    body = rows[2:]  # rows[1] is the |---| separator
    th = "".join(f"<th>{inline(c.strip())}</th>" for c in head)
    trs = "".join(
        "<tr>" + "".join(f"<td>{inline(c.strip())}</td>" for c in r) + "</tr>"
        for r in body)
    return (f'<div class="table-wrap"><table><thead><tr>{th}</tr></thead>'
            f"<tbody>{trs}</tbody></table></div>")


def _split_row(line: str) -> list[str]:
    cells = line.strip().strip("|").split("|")
    return [c.strip() for c in cells]


def convert(md: str) -> tuple[str, list[tuple[int, str, str]], str]:
    """Return (title, toc entries, body HTML).  toc entries are (level, id, text)."""
    lines = md.splitlines()
    title = "User Manual"
    toc: list[tuple[int, str, str]] = []
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]

        if line.startswith("```"):                      # fenced code block
            i += 1
            block: list[str] = []
            while i < n and not lines[i].startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1                                       # skip closing fence
            out.append("<pre><code>" +
                       html.escape("\n".join(block), quote=False) + "</code></pre>")
            continue

        m = _HEADING.match(line)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            if level == 1:
                title = text
                out.append(f"<h1>{inline(text)}</h1>")
            else:
                sid = slugify(text)
                if level in (2, 3):
                    toc.append((level, sid, text))
                out.append(f'<h{level} id="{sid}">{inline(text)}</h{level}>')
            i += 1
            continue

        if line.strip().startswith("|") and i + 1 < n and set(lines[i + 1].strip()) <= set("|-: "):
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(_split_row(lines[i]))
                i += 1
            out.append(_render_table(rows))
            continue

        lm = _LIST_ITEM.match(line)
        if lm:
            ordered = lm.group(2)[0].isdigit()
            items: list[tuple[str, list[str]]] = []
            while i < n:
                im = _LIST_ITEM.match(lines[i])
                if im:
                    items.append((im.group(1), [im.group(3)]))
                    i += 1
                elif lines[i].strip() and lines[i].startswith(" ") and items:
                    items[-1][1].append(lines[i].strip())    # wrapped continuation line
                    i += 1
                else:
                    break
            out.append(_render_list(items, ordered))
            continue

        if not line.strip():                             # blank line
            i += 1
            continue

        para = [line]                                    # a paragraph: gather until blank/special
        i += 1
        while i < n and lines[i].strip() and not _HEADING.match(lines[i]) \
                and not lines[i].startswith("```") and not _LIST_ITEM.match(lines[i]) \
                and not lines[i].strip().startswith("|"):
            para.append(lines[i])
            i += 1
        out.append(f"<p>{inline(' '.join(s.strip() for s in para))}</p>")

    return title, toc, "\n".join(out)


def render_toc(toc: list[tuple[int, str, str]]) -> str:
    parts = ['<nav class="toc" aria-label="Table of contents"><h2>Contents</h2><ul>']
    for level, sid, text in toc:
        cls = "toc-sub" if level == 3 else "toc-top"
        parts.append(f'<li class="{cls}"><a href="#{sid}">{html.escape(text)}</a></li>')
    parts.append("</ul></nav>")
    return "".join(parts)


_CSS = """
:root { color-scheme: light dark; --bg:#1e1e1e; --fg:#ffffff; --muted:#c8c8c8;
  --accent:#7ec8ff; --card:#2a2a2d; --border:#4a4a4a; --code:#ffd479; }
@media (prefers-color-scheme: light) { :root { --bg:#ffffff; --fg:#141414;
  --muted:#3a3a3a; --accent:#0b5fb0; --card:#f0f0f2; --border:#c9c9c9; --code:#8a4b00; } }
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin:0; background:var(--bg); color:var(--fg); font-size:19px; line-height:1.65;
  font-family: "Segoe UI", system-ui, sans-serif; }
.skip { position:absolute; left:-999px; top:0; background:var(--accent); color:#000;
  padding:.5rem 1rem; z-index:10; }
.skip:focus { left:0; }
.layout { display:flex; align-items:flex-start; gap:2rem; max-width:1200px; margin:0 auto;
  padding:1.5rem; }
.toc { position:sticky; top:1rem; flex:0 0 300px; background:var(--card);
  border:1px solid var(--border); border-radius:10px; padding:1rem 1.25rem;
  max-height:calc(100vh - 2rem); overflow:auto; }
.toc h2 { margin:.2rem 0 .6rem; font-size:1.15rem; }
.toc ul { list-style:none; margin:0; padding:0; }
.toc li { margin:.15rem 0; }
.toc-sub { padding-left:1.1rem; font-size:.95em; }
.toc a { color:var(--accent); text-decoration:none; display:block; padding:.25rem .4rem;
  border-radius:6px; }
.toc a:hover, .toc a:focus { background:rgba(126,200,255,.18); text-decoration:underline; }
main { flex:1 1 auto; min-width:0; }
h1 { font-size:2.1rem; line-height:1.2; margin:.2rem 0 1rem; }
h2 { font-size:1.6rem; margin:2rem 0 .6rem; padding-bottom:.3rem;
  border-bottom:2px solid var(--border); scroll-margin-top:1rem; }
h3 { font-size:1.25rem; margin:1.4rem 0 .5rem; color:var(--fg); scroll-margin-top:1rem; }
p { margin:.7rem 0; }
a { color:var(--accent); }
ul, ol { margin:.6rem 0; padding-left:1.6rem; }
li { margin:.4rem 0; }
code { background:var(--card); color:var(--code); padding:.1em .35em; border-radius:5px;
  font-family: "Cascadia Code", Consolas, monospace; font-size:.92em; }
pre { background:var(--card); border:1px solid var(--border); border-radius:10px;
  padding:1rem; overflow:auto; }
pre code { background:none; color:var(--fg); padding:0; }
.table-wrap { overflow-x:auto; margin:1rem 0; }
table { border-collapse:collapse; width:100%; }
th, td { border:1px solid var(--border); padding:.55rem .7rem; text-align:left;
  vertical-align:top; }
th { background:var(--card); }
strong { color:var(--fg); }
@media (max-width: 820px) { .layout { flex-direction:column; }
  .toc { position:static; flex-basis:auto; width:100%; max-height:none; } }
"""


def render_page(title: str, toc: list, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<a class="skip" href="#content">Skip to content</a>
<div class="layout">
{render_toc(toc)}
<main id="content">
{body}
</main>
</div>
</body>
</html>
"""


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parent.parent
    src = root / "docs" / "user-manual.md"
    dst = root / "docs" / "user-manual.html"
    if not src.is_file():
        print(f"missing {src}", file=sys.stderr)
        return 1
    _slug_seen.clear()
    title, toc, body = convert(src.read_text(encoding="utf-8"))
    dst.write_text(render_page(title, toc, body), encoding="utf-8")
    print(f"wrote {dst} ({len(toc)} sections)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
