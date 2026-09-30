---
name: libro-a-podcasts
description: Convierte un libro en PDF en podcasts de NotebookLM (~15 min) por capítulo o grupo de capítulos, en inglés, francés, portugués de Brasil o italiano. Usar cuando Álvaro dé la ruta de un PDF y pida podcasts, audio overviews o NotebookLM por capítulos.
---

# Libro PDF → secciones → NotebookLM → podcasts

Flujo: (1) ruta del PDF → (2) plan de secciones (capítulos, agrupando los cortos para que cada podcast tenga material suficiente) → (3) PDFs de sección en `<carpeta del PDF>/capitulos/` → (4) un cuaderno de NotebookLM por sección → (5) un podcast de ~15 min por cuaderno → (6) en el idioma elegido, descargado en `<carpeta del PDF>/podcasts/<idioma>/` como `NN - Título (fr).m4a`.

Se ejecuta en el PC de Álvaro (Claude Code, Windows). NotebookLM (ahora "Gemini Notebook") no tiene API pública para cuentas personales; se usa la librería no oficial `notebooklm-py`, que puede romperse si Google cambia sus endpoints.

## 0. Preparación (solo si falta algo)

1. Scripts: están en la subcarpeta `scripts/` de la carpeta de esta skill (normalmente `~/.claude/skills/libro-a-podcasts/scripts/`). En adelante, `$S` = esa carpeta. No los reescribas; si falta alguno, dile a Álvaro que haga `git pull` en el repo de la skill.
2. Dependencias: `python -c "import pypdf, notebooklm"`. Si falla: `pip install -r "$S/../requirements.txt"` (y si el login lo pide, `python -m playwright install chromium`).
3. Sesión de Google: `notebooklm auth check --test`. Si no está autenticado, pide a Álvaro que ejecute él `! notebooklm login` (abre el navegador; inicia sesión con la cuenta que quiera usar para NotebookLM) y espera a que confirme. No intentes hacer tú el login.

## 1. Entradas

- Ruta del PDF (obligatoria). Acepta rutas de Windows con espacios (`H:\Mi unidad\...`); entrecomíllalas siempre.
- Idioma del podcast: si no lo ha dicho, pregúntalo con AskUserQuestion — opciones: Inglés (`en`), Francés (`fr`), Portugués de Brasil (`pt-BR`), Italiano (`it`). Si pide varios, ejecuta el paso 4 una vez por idioma (los cuadernos se reutilizan).
- Opcionales (valores por defecto sin preguntar): formato `deep-dive` (conversación entre dos presentadores), duración `default` (≈10-20 min; usar `long` si los podcasts salen cortos).

## 2. Plan de secciones

```
python "$S/split_book.py" plan "<ruta.pdf>"
```

Lee los marcadores (outline) del PDF, detecta partes y capítulos, cuenta palabras y agrupa capítulos consecutivos de la misma parte hasta ~7 000-16 000 palabras por sección (un capítulo largo va solo; los cortos se juntan). Omite portada, índice, notas, bibliografía, etc. Guarda `capitulos/plan.json`.

Revisa la salida antes de seguir:
- Si el nivel de capítulo es incorrecto, repite con `--level 0` o `--level 1`. Si prefieres permitir juntar capítulos de partes distintas: `--cross-parts`. Ajusta `--min-words/--max-words` si las secciones salen demasiado pequeñas o grandes.
- **Sin outline** (`outline_found: false`): ejecuta `python "$S/split_book.py" pages "<ruta.pdf>"`, localiza dónde empieza cada capítulo leyendo las cabeceras de página, y escribe tú la lista `sections` en `plan.json` (campos `n`, `title`, `chapters`, `start_page`, `end_page` 1-based inclusivos, `words` aproximado, `filename` tipo `"03 - Título.pdf"`).
- Si casi todas las páginas tienen 0 palabras, el PDF es escaneado: avisa de que hay que pasarle OCR antes.
- Si una sección supera ~200 MB o 500 000 palabras (límites de NotebookLM), divídela.

Muestra a Álvaro la tabla de secciones (nº, capítulos incluidos, páginas, palabras) y pide confirmación antes de crear cuadernos: cada sección consume un cuaderno (máx. 100 en cuenta gratuita) y presupuesto de uso.

## 3. Crear los PDFs

```
python "$S/split_book.py" split "<carpeta>/capitulos/plan.json"
```

Escribe un PDF por sección en `capitulos/` (no sobrescribe los existentes salvo `--force`).

## 4. Cuadernos y podcasts

```
python "$S/make_podcasts.py" "<carpeta>/capitulos/plan.json" --lang fr
```

Por cada sección: crea el cuaderno `"<Libro> — NN. <Título>"`, sube el PDF, lanza el Audio Overview en el idioma elegido con instrucciones de ~15 min centradas en esa sección, espera y descarga `NN - Título (fr).m4a` en `podcasts/<idioma>/` (espanol, frances, portugues, italiano, ingles). Procesa 2 en paralelo (`--concurrency`). Cada podcast tarda unos 5-15 min en generarse, así que un libro entero puede llevar más de una hora: lánzalo en segundo plano (timeout largo) y consulta la salida periódicamente.

- El progreso queda en `capitulos/podcasts_state.json`. Si se para por **límite de uso** (NotebookLM repone el presupuesto cada ~5 h, con tope semanal), o por un error, basta con volver a ejecutar el mismo comando más tarde: continúa donde lo dejó y no duplica cuadernos. Ofrece programarlo si procede.
- `--only 3,4` para rehacer secciones concretas (borra antes su entrada `"N|idioma"` del state si quieres regenerar el audio).
- `--no-download` si solo los quiere en la app de NotebookLM.

## 5. Cierre

Resume en 2-3 líneas: cuántas secciones, cuántos podcasts listos por idioma, cuáles fallaron y por qué, y dónde están (`capitulos/` dentro de la carpeta del libro). Si la duración real de los audios se aleja mucho de 15 min, sugiere `--length long` o ajustar el tamaño de las secciones.

