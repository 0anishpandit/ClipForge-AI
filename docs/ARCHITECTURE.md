# Architecture

ClipForge is a Streamlit app (`app.py`) on top of a plain Python package (`clipforge/`).
All real logic lives in the package, split into layers that depend only downward.
Only `clipforge/ui/` imports Streamlit, so every other layer can be tested and reused
(CLI, API, another UI) without a browser.

## Layout

```
app.py                    Entry point: `streamlit run app.py`. Just calls clipforge.ui.main.run()
clipforge/
  config.py               Settings dataclass; defaults + CLIPFORGE_* env vars + optional .env
  errors.py               ClipForgeError and subclasses (user-facing failures)
  utils.py                fmt_time, safe_float
  logging_config.py       One-time logger setup (replaces print debugging)

  transcript/             Getting and preparing text
    youtube.py              URL -> video id; caption fetch -> rows
    formatting.py           Rows -> AI prompt lines / downloadable .txt
    chunking.py             Split long transcripts into overlapping chunks

  ai/                     Highlight detection (local Ollama)
    ollama.py               OllamaClient: list_models(), chat_json()
    prompts.py              Prompt templates
    evidence.py             Does the AI's quote really appear near the moment?
    validation.py           Validate one candidate, expand to target length, score
    dedup.py                Drop candidates covering the same moment
    analyzer.py             analyze_transcript(): the pipeline, returns AnalysisResult

  rendering/              Vertical video output (FFmpeg)
    regions.py              Percent crop regions -> validated -> crop filter
    layouts.py              The four 1080x1920 filter graphs
    ffmpeg.py               Locate FFmpeg, build command, run it
    renderer.py             render_clips(): validate, render each clip, return ZIP bytes

  ui/                     Streamlit only
    main.py                 Page composition; the only place layers are wired together
    state.py                Session-state keys and helpers
    sidebar.py              Language / clip limits / Ollama settings
    transcript_panel.py     Transcript table + download
    clips_panel.py          Editable clip table + plan download
    render_panel.py         Upload, layout controls, render + download
tests/                    pytest suite (see CHANGES_AND_VERIFICATION.md)
scripts/                  setup.ps1, run.ps1 (Windows PowerShell)
```

## Dependency direction

```
            ui
        /    |     \
      ai  rendering  transcript
        \    |     /
   config · errors · utils
(ai also uses transcript.chunking/formatting; nothing else crosses between siblings)
```

`ai` and `rendering` never import each other, and nothing imports `ui`.
There are no import cycles (every module imports cleanly on its own).

## Data flow

1. **Extract** – `ui.main` → `transcript.youtube.get_video_id` / `fetch_transcript` →
   rows `{start_sec, end_sec, timestamp, text}` stored in `st.session_state`.
2. **Analyze** – `ai.analyzer.analyze_transcript(rows, client, ...)`:
   `chunking.split_into_chunks` → for each chunk, `client.chat_json` (one retry with an
   alternate prompt) → `validation.validate_clip` on every candidate → `dedup` → rank by
   quality score → top *N*.
3. **Review** – `ui.clips_panel` shows an editable table; the edited rows go on.
4. **Render** – `ui.render_panel` streams the upload to a temp file, then
   `rendering.renderer.render_clips(source_path, rows, layout_settings)` validates the rows,
   builds the filter graph (`layouts`), runs FFmpeg per clip and returns a ZIP as bytes.

### Why candidates are validated

Small local models invent timestamps and quotes. `validate_clip` rejects a candidate unless
its timestamps are sane and inside the chunk/video, its quoted evidence matches the real
transcript near that moment (≥35 % of its words), and its title/hook/reason are non-trivial.
The AI's "core moment" is then widened evenly to the minimum clip length. Rejection counts
are logged and reported when nothing survives.

## Design decisions

- **Dependency injection at the AI boundary.** `analyze_transcript` takes any object with
  `chat_json(system, user)`. Tests use a fake; a different backend only needs that method.
- **Rows stay plain dicts.** They go straight into pandas / `st.data_editor` and JSON
  downloads, so a model class would add conversion code for no gain.
- **Standard library HTTP for Ollama** – no `requests`/`openai` dependency.
- **Rendering takes a file path, not a Streamlit upload,** so it has no UI dependency and
  large videos are streamed to disk instead of held in memory.
- **Expected failures are `ClipForgeError`s;** the UI catches those and shows the message.
  Genuine bugs still surface as exceptions.
- **Layout names are constants** in `rendering/layouts.py`, shared by UI and renderer.

## Extending

- *New layout:* add a constant and a branch in `rendering/layouts.py`, add it to
  `ALL_LAYOUTS`, and add a case to `tests/test_rendering.py::LAYOUT_CASES`.
- *Different AI backend:* implement `chat_json(system_prompt, user_prompt) -> {"clips": [...]}`
  and construct it in `ui/main.py`.
- *Video/audio analysis* (e.g. loudness or scene-change detection): add a new top-level
  package (e.g. `clipforge/analysis/`) that produces candidate windows in the same clip-dict
  shape, and merge them in the analyze step. It was not created now because no such code exists yet.
