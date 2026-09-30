#!/usr/bin/env python3
"""Create one NotebookLM notebook per section PDF and generate a ~15 min podcast.

  python make_podcasts.py "<outdir>/plan.json" --lang fr [--length default|long|short]
                          [--format deep-dive|brief|critique|debate] [--only 3,4,7]
                          [--concurrency 2] [--no-download]

Languages accepted: en, fr, pt-BR (pt_BR), it, es  (any NotebookLM code also works).

Resumable: progress is stored in <outdir>/podcasts_state.json. Re-running skips
finished sections and re-attaches to podcasts still being generated, so after a
usage-limit stop just run the same command again later.

Requires: notebooklm-py, authenticated once with `notebooklm login`.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

try:
    from notebooklm import AudioFormat, AudioLength, NotebookLMClient
except ImportError:  # pragma: no cover
    sys.exit('Falta notebooklm-py. Instala con:  pip install "notebooklm-py[browser]"  y luego  notebooklm login')

LANGS = {
    "en": ("en", "English"),
    "fr": ("fr", "French"),
    "pt-br": ("pt_BR", "Brazilian Portuguese"),
    "pt_br": ("pt_BR", "Brazilian Portuguese"),
    "it": ("it", "Italian"),
    "es": ("es", "Spanish"),
}
# Audio goes to <book folder>/podcasts/<folder>/
AUDIO_FOLDERS = {"en": "ingles", "fr": "frances", "pt_BR": "portugues", "it": "italiano", "es": "espanol"}
FORMATS = {"deep-dive": AudioFormat.DEEP_DIVE, "brief": AudioFormat.BRIEF,
           "critique": AudioFormat.CRITIQUE, "debate": AudioFormat.DEBATE}
LENGTHS = {"short": AudioLength.SHORT, "default": AudioLength.DEFAULT, "long": AudioLength.LONG}

INSTRUCTIONS = (
    "This source is one section of the book \"{book}\": {section}. "
    "Create an engaging conversation of about 15 minutes, entirely in {lang_name}. "
    "Cover the main ideas, stories and examples of this section in the order the author presents them, "
    "explain difficult concepts simply, and do not discuss other parts of the book as if they were in the source."
)


def load_json(p: Path, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


class State:
    def __init__(self, path: Path):
        self.path = path
        self.data = load_json(path, {})
        self.lock = asyncio.Lock()

    def get(self, key):
        return self.data.setdefault(key, {})

    async def save(self):
        async with self.lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


async def process(client, plan, sec, a, lang_code, lang_name, state: State, sem):
    outdir = Path(plan["outdir"])
    pdf = outdir / sec["filename"]
    key = f"{sec['n']}|{lang_code}"
    st = state.get(key)
    audio_dir = outdir.parent / "podcasts" / AUDIO_FOLDERS.get(lang_code, lang_code)
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_path = audio_dir / f"{pdf.stem} ({lang_code}).m4a"
    if st.get("status") == "done" and (a.no_download or audio_path.exists()):
        log(f"[{sec['n']}] ya hecho → {audio_path.name}")
        return "done"
    if not pdf.exists():
        log(f"[{sec['n']}] FALTA el PDF {pdf.name} (ejecuta primero split_book.py split)")
        return "missing"

    async with sem:
        try:
            # 1) Notebook (one per section, shared by all languages of that section)
            nb_key = f"nb|{sec['n']}"
            nb_st = state.get(nb_key)
            if not nb_st.get("notebook_id"):
                title = f"{plan['book_title']} — {sec['n']:02d}. {sec['title']}"[:100]
                nb = await client.notebooks.create(title)
                nb_st["notebook_id"] = nb.id
                await state.save()
                log(f"[{sec['n']}] cuaderno creado: {title}")
            nb_id = nb_st["notebook_id"]

            # 2) Source
            if not nb_st.get("source_id"):
                src = await client.sources.add_file(nb_id, str(pdf), wait=True, wait_timeout=600,
                                                    title=sec["title"][:100])
                nb_st["source_id"] = src.id
                await state.save()
                log(f"[{sec['n']}] PDF subido y procesado")

            # 3) Audio generation
            if not st.get("artifact_id"):
                status = await client.artifacts.generate_audio(
                    nb_id,
                    language=lang_code,
                    instructions=INSTRUCTIONS.format(book=plan["book_title"], section=sec["title"],
                                                     lang_name=lang_name),
                    audio_format=FORMATS[a.format],
                    audio_length=LENGTHS[a.length],
                )
                if status.is_failed or not status.task_id:
                    raise RuntimeError(f"no se pudo lanzar ({status.error_code}: {status.error})")
                st.update(artifact_id=status.task_id, status="generating", notebook_id=nb_id)
                await state.save()
                log(f"[{sec['n']}] podcast en generación ({lang_name})…")

            # 4) Wait
            if st.get("status") != "done":
                final = await client.artifacts.wait_for_completion(
                    nb_id, st["artifact_id"], initial_interval=15, max_interval=60, timeout=a.timeout)
                if not final.is_complete:
                    raise RuntimeError(f"estado final {final.status} {final.error or ''}")
                st["status"] = "done"
                await state.save()

            # 5) Download into podcasts/<language>/
            if not a.no_download and not audio_path.exists():
                await client.artifacts.download_audio(nb_id, str(audio_path), st["artifact_id"])
                st["audio"] = str(audio_path)
                await state.save()
            log(f"[{sec['n']}] ✔ listo → {audio_path.name if not a.no_download else 'en NotebookLM'}")
            return "done"
        except Exception as e:  # keep going with the other sections
            msg = str(e)
            st["last_error"] = msg[:500]
            await state.save()
            limit = any(w in msg.lower() for w in ("rate", "quota", "limit", "resource_exhausted", "displayable"))
            log(f"[{sec['n']}] ✖ {'LÍMITE DE USO — ' if limit else ''}{msg[:300]}")
            return "limit" if limit else "error"


async def main_async(a):
    plan_path = Path(a.plan).expanduser().resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    lk = a.lang.lower()
    lang_code, lang_name = LANGS.get(lk, (a.lang, a.lang))
    sections = plan["sections"]
    if a.only:
        wanted = {int(x) for x in a.only.split(",") if x.strip()}
        sections = [s for s in sections if s["n"] in wanted]
    state = State(Path(plan["outdir"]) / "podcasts_state.json")
    sem = asyncio.Semaphore(a.concurrency)
    log(f"{len(sections)} secciones · idioma {lang_name} ({lang_code}) · {a.format}/{a.length}")
    async with NotebookLMClient.from_storage() as client:
        results = await asyncio.gather(*[process(client, plan, s, a, lang_code, lang_name, state, sem)
                                         for s in sections])
    summary = {k: results.count(k) for k in set(results)}
    log(f"Resumen: {summary}")
    if summary.get("limit") or summary.get("error"):
        log("Vuelve a ejecutar el mismo comando más tarde: continuará donde se quedó.")
    print(json.dumps({"summary": summary, "state": str(state.path)}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan")
    ap.add_argument("--lang", required=True, help="en | fr | pt-BR | it")
    ap.add_argument("--length", choices=list(LENGTHS), default="default")
    ap.add_argument("--format", choices=list(FORMATS), default="deep-dive")
    ap.add_argument("--only", default="", help="Números de sección separados por comas")
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--timeout", type=float, default=2400, help="Segundos máx. de espera por podcast")
    ap.add_argument("--no-download", action="store_true")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
