# libro-a-podcasts

Skill de Claude Code que convierte un libro en PDF en podcasts de NotebookLM (~15 min) por capítulo o grupo de capítulos, en inglés, francés, portugués de Brasil o italiano.

## Flujo

1. `scripts/split_book.py plan` lee los marcadores del PDF y propone secciones: los capítulos cortos se juntan hasta tener entre 7.000 y 16.000 palabras. Guarda el plan en `plan.json`.
2. `scripts/split_book.py split` escribe un PDF por sección en `<carpeta del libro>/capitulos/`.
3. `scripts/make_podcasts.py` crea un cuaderno de NotebookLM por sección, genera el Audio Overview en el idioma elegido y descarga `NN - Título (idioma).m4a` junto a su PDF. Si se interrumpe, al relanzarlo continúa donde lo dejó (`podcasts_state.json`).

## Instalación

```bash
# Windows (Git Bash) / macOS / Linux
git clone <url-del-repo> ~/.claude/skills/libro-a-podcasts
pip install -r ~/.claude/skills/libro-a-podcasts/requirements.txt
notebooklm login          # una vez; abre el navegador para iniciar sesión en Google
```

(Si `notebooklm login` lo pide: `python -m playwright install chromium`.)

## Uso

En Claude Code: *"Hazme los podcasts en francés de H:\Mi unidad\...\libro.pdf"*.

Uso manual:

```bash
S=~/.claude/skills/libro-a-podcasts/scripts
python $S/split_book.py plan  "ruta/libro.pdf"
python $S/split_book.py split "ruta/capitulos/plan.json"
python $S/make_podcasts.py    "ruta/capitulos/plan.json" --lang fr   # en | fr | pt-BR | it
```

Opciones útiles: `--length long`, `--format debate`, `--only 3,4`, `--no-download`, `--cross-parts`, `--min-words/--max-words`.

## Avisos

- [notebooklm-py](https://github.com/teng-lin/notebooklm-py) es una librería no oficial y puede dejar de funcionar si Google cambia la web de NotebookLM.
- Cada sección ocupa un cuaderno; la cuenta gratuita permite 100. El presupuesto de uso se repone cada ~5 h.
