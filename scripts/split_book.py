#!/usr/bin/env python3
"""Split a book PDF into chapter/section PDFs sized for ~15-minute podcasts.

Two steps, so the plan can be reviewed before anything is written:

  python split_book.py plan  "<book.pdf>" [--min-words 7000] [--max-words 16000]
                             [--level N] [--cross-parts] [--outdir DIR]
      -> writes <outdir>/plan.json and prints a summary table.

  python split_book.py split "<outdir>/plan.json"
      -> writes one PDF per section into <outdir> (default: <pdf folder>/capitulos).

plan.json can be edited by hand between the two steps (rename sections, change
page ranges, move chapters between sections, drop front/back matter).

Requires: pypdf  (pip install pypdf)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:  # pragma: no cover
    sys.exit("Falta pypdf. Instala con:  pip install pypdf")

SKIP_PATTERNS = re.compile(
    r"^(contents|table of contents|index|notes|bibliography|references|select bibliography|"
    r"acknowledg|copyright|cover|title page|also by|about the author|dedication|"
    r"índice|indice|notas|bibliografía|bibliografia|agradecimientos|créditos|creditos|"
    r"portada|sumario|table des matières|sommaire|remerciements)",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------- outline
def flatten_outline(reader: PdfReader):
    """Return [(level, title, page_index)] in document order."""
    out = []

    def walk(items, level):
        for it in items:
            if isinstance(it, list):
                walk(it, level + 1)
                continue
            try:
                page = reader.get_destination_page_number(it)
            except Exception:
                continue
            title = (it.title or "").strip()
            if page is not None and page >= 0 and title:
                out.append((level, title, page))

    try:
        walk(reader.outline, 0)
    except Exception:
        return []
    return out


def pick_chapter_level(entries, forced: int | None):
    if forced is not None:
        return forced
    levels = sorted({lv for lv, _, _ in entries})
    counts = {lv: sum(1 for e in entries if e[0] == lv) for lv in levels}
    # Top level with "many" entries (>=6) are chapters; if the top level has few
    # entries but the next has many, top level = parts, next = chapters.
    if counts.get(0, 0) >= 6 or len(levels) == 1:
        return 0
    return 1 if counts.get(1, 0) >= 3 else 0


def page_words(reader: PdfReader, i: int) -> int:
    try:
        return len((reader.pages[i].extract_text() or "").split())
    except Exception:
        return 0


# --------------------------------------------------------------------------- planning
def build_chapters(reader, entries, ch_level):
    n_pages = len(reader.pages)
    chapters, current_part = [], None
    # Positions of every entry at level <= ch_level delimit chapter ends.
    boundaries = [(lv, t, p) for lv, t, p in entries if lv <= ch_level]
    for idx, (lv, title, start) in enumerate(boundaries):
        if lv < ch_level:  # a part heading
            current_part = title
            continue
        end = n_pages - 1
        for lv2, _, p2 in boundaries[idx + 1:]:
            if p2 > start:
                end = p2 - 1
                break
            if p2 == start and lv2 <= ch_level:
                # Next entry starts on the same page: keep at least 1 page.
                end = start
                break
        chapters.append({"title": title, "part": current_part, "start": start, "end": max(start, end)})
    # Deduplicate same-start entries (keep first).
    seen, uniq = set(), []
    for c in chapters:
        if c["start"] in seen:
            continue
        seen.add(c["start"])
        uniq.append(c)
    for c in uniq:
        c["words"] = sum(page_words(reader, i) for i in range(c["start"], c["end"] + 1))
        c["skip"] = bool(SKIP_PATTERNS.match(c["title"]))
    return uniq


def group(chapters, min_words, max_words, cross_parts):
    kept = [c for c in chapters if not c["skip"]]
    sections, cur = [], []

    def cur_words():
        return sum(c["words"] for c in cur)

    for c in kept:
        if cur:
            part_change = (not cross_parts) and c["part"] != cur[-1]["part"]
            too_big = cur_words() + c["words"] > max_words
            if part_change or too_big or cur_words() >= min_words:
                sections.append(cur)
                cur = []
        cur.append(c)
    if cur:
        sections.append(cur)

    # Merge a too-small trailing group of each part into its predecessor if it fits.
    merged = []
    for s in sections:
        w = sum(c["words"] for c in s)
        if merged and w < min_words * 0.5:
            prev = merged[-1]
            same_part = cross_parts or prev[-1]["part"] == s[0]["part"]
            if same_part and sum(c["words"] for c in prev) + w <= max_words * 1.15:
                prev.extend(s)
                continue
        merged.append(s)
    return merged


def safe_name(text: str, maxlen: int = 80) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text).strip().rstrip(".")
    text = re.sub(r"\s+", " ", text)
    return text[:maxlen].strip() or "seccion"


def section_title(chs):
    if len(chs) == 1:
        return chs[0]["title"]
    return f"{chs[0]['title']} – {chs[-1]['title']}"


def cmd_plan(a):
    pdf = Path(a.pdf).expanduser().resolve()
    if not pdf.exists():
        sys.exit(f"No existe: {pdf}")
    reader = PdfReader(str(pdf))
    outdir = Path(a.outdir).expanduser().resolve() if a.outdir else pdf.parent / "capitulos"
    entries = flatten_outline(reader)
    plan = {
        "source_pdf": str(pdf),
        "book_title": (reader.metadata.title if reader.metadata and reader.metadata.title else pdf.stem),
        "outdir": str(outdir),
        "total_pages": len(reader.pages),
        "min_words": a.min_words,
        "max_words": a.max_words,
        "outline_found": bool(entries),
        "chapters": [],
        "sections": [],
    }
    if not entries:
        plan["note"] = ("El PDF no tiene marcadores (outline). Detecta los capítulos leyendo el texto "
                        "(p. ej. con 'python split_book.py pages') y rellena 'sections' a mano.")
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"outline_found": False, "plan": str(outdir / "plan.json")}, ensure_ascii=False))
        return

    ch_level = pick_chapter_level(entries, a.level)
    chapters = build_chapters(reader, entries, ch_level)
    groups = group(chapters, a.min_words, a.max_words, a.cross_parts)
    plan["chapter_level"] = ch_level
    plan["chapters"] = chapters
    width = max(2, len(str(len(groups))))
    for i, g in enumerate(groups, 1):
        title = section_title(g)
        plan["sections"].append({
            "n": i,
            "title": title,
            "part": g[0]["part"],
            "chapters": [c["title"] for c in g],
            "start_page": g[0]["start"] + 1,  # 1-based, inclusive
            "end_page": g[-1]["end"] + 1,
            "words": sum(c["words"] for c in g),
            "filename": f"{str(i).zfill(width)} - {safe_name(title)}.pdf",
        })
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Libro: {plan['book_title']}  ({plan['total_pages']} págs)  nivel de capítulo: {ch_level}")
    skipped = [c["title"] for c in chapters if c["skip"]]
    if skipped:
        print("Omitidos (portada/índice/notas…):", "; ".join(skipped))
    print(f"{len(groups)} secciones  (objetivo {a.min_words}-{a.max_words} palabras):")
    for s in plan["sections"]:
        print(f"  {s['n']:>3}. págs {s['start_page']:>4}-{s['end_page']:<4} {s['words']:>6} pal  "
              f"[{len(s['chapters'])} cap]  {s['title']}")
    print(f"\nPlan guardado en: {outdir / 'plan.json'}")


def cmd_split(a):
    plan_path = Path(a.plan).expanduser().resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    reader = PdfReader(plan["source_pdf"])
    outdir = Path(plan["outdir"])
    outdir.mkdir(parents=True, exist_ok=True)
    written = []
    for s in plan["sections"]:
        dest = outdir / s["filename"]
        if dest.exists() and not a.force:
            written.append(str(dest))
            continue
        w = PdfWriter()
        for i in range(s["start_page"] - 1, s["end_page"]):
            w.add_page(reader.pages[i])
        w.add_metadata({"/Title": f"{plan['book_title']} — {s['title']}"})
        with open(dest, "wb") as fh:
            w.write(fh)
        written.append(str(dest))
    print(json.dumps({"outdir": str(outdir), "files": written}, ensure_ascii=False, indent=2))


def cmd_pages(a):
    """Print the first line(s) of each page — helps find chapter starts without an outline."""
    reader = PdfReader(a.pdf)
    for i, p in enumerate(reader.pages, 1):
        txt = (p.extract_text() or "").strip().splitlines()
        head = " | ".join(l.strip() for l in txt[: a.lines] if l.strip())
        print(f"{i:>4}: {head[:160]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("pdf")
    p.add_argument("--min-words", type=int, default=7000)
    p.add_argument("--max-words", type=int, default=16000)
    p.add_argument("--level", type=int, default=None, help="Nivel del outline que son capítulos (0=superior)")
    p.add_argument("--cross-parts", action="store_true", help="Permitir juntar capítulos de partes distintas")
    p.add_argument("--outdir", default=None)
    p.set_defaults(func=cmd_plan)
    s = sub.add_parser("split")
    s.add_argument("plan")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_split)
    g = sub.add_parser("pages")
    g.add_argument("pdf")
    g.add_argument("--lines", type=int, default=2)
    g.set_defaults(func=cmd_pages)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
