# Changes, bugs fixed, and verification

## What was restructured

The original project was one 1,366-line `app.py` (plus README, requirements, `.env.example`,
`.streamlit/config.toml`, `.gitignore`, and a 430 MB `.venv`). It mixed Streamlit UI,
transcript fetching, Ollama calls, clip validation, FFmpeg filters and rendering in one file.
It is now ~1,500 lines across 23 small modules plus a 9-line `app.py` (largest module: 157 lines) in four layers
(`transcript`, `ai`, `rendering`, `ui`) plus shared `config`/`errors`/`utils`.
See [ARCHITECTURE.md](ARCHITECTURE.md).

Original file dispositions:

| Original | Result |
|----------|--------|
| `app.py` | Split into the package; `app.py` is now a 9-line launcher |
| `requirements.txt` | Rewritten (see below) |
| `README.md` | Rewritten; it described an OpenAI workflow the code never used |
| `.env.example` | Rewritten; its `OPENAI_MODEL` was never read |
| `.streamlit/config.toml` | Kept unchanged in content (2 GB upload limit) |
| `.gitignore` | Fixed (see below) |
| `.venv/` | **Not carried over.** It was bound to `C:\Users\anish\...` and Python 3.14 so it cannot be moved; recreate it with `scripts\setup.ps1`. It also contained an unused `openai` package |

Backups: your uploaded ZIP is untouched, and `clipforge_ai_original_backup.zip` holds the
original source files (without `.venv`).

## Bugs fixed

1. **Silent corrupt clips.** A clip starting past the end of the video made FFmpeg exit
   successfully with a 262-byte file containing no streams, which the original zipped as if
   it were fine. Now detected and reported as an error (test added).
2. **Windows FFmpeg output decoding.** `subprocess.run(text=True)` uses the Windows locale
   code page and can crash on non-ASCII FFmpeg output; now decoded as UTF-8 with replacement.
3. **Download button vanished after rendering.** The rendered ZIP lived only in the run that
   produced it, so clicking *Download* (which reruns the script) removed the button. The
   archive is now kept in session state, and download buttons no longer trigger a rerun.
4. **Stale table edits.** The clip editor reused one widget key, so edits from a previous
   analysis could leak into new results. The key now changes with every analysis.
5. **Misleading error when Ollama is down.** If every request failed, the app reported
   "no sufficiently supported clip candidates". It now reports the real connection error, and
   warns when only some chunks failed.
6. **Wrong region name in errors.** Facecam/gameplay problems always said "video region";
   they now name the right region.
7. **Table cells with no title** (NaN) could produce files named `clip_01_nan.mp4`; now `highlight`.
8. **`.gitignore` excluded `.streamlit/`,** which would drop the upload-limit config from version control.
9. **Dependencies were wrong:** the code uses `width="stretch"`, which needs a newer Streamlit
   than the `>=1.36` pin allowed; now `>=1.50`. No new runtime dependencies were added.
10. **Large uploads held fully in memory** (`getbuffer()` copy); now streamed to a temp file.
11. **README/UI/code disagreed** (OpenAI vs Ollama); docs now match the code.

## Improvements

- Settings via `CLIPFORGE_*` environment variables or `.env` (Ollama URL, model, timeout,
  FFmpeg path, log level); the Ollama URL was hardcoded before. No machine-specific paths anywhere.
- `print` debugging replaced with `logging`.
- Per-clip render progress bar.
- Typed error classes; the UI shows expected errors and does not hide real bugs behind them.
- FFmpeg runs with `-nostdin` and warning-level output so failures are short and readable.
- `scripts/setup.ps1` / `scripts/run.ps1` for Windows PowerShell (run via the venv's Python,
  so no activation or execution-policy changes are needed beyond `-ExecutionPolicy Bypass`).
- 91 automated tests (there were none).

Behavior that is intentionally unchanged: prompts, validation thresholds, scoring, chunking,
de-duplication, the four layouts, FFmpeg filter graphs and encoding settings, and every UI
control and label.

## Verification

Environment: Linux sandbox, Python 3.12.3, Streamlit 1.67.0, pandas 3.0.6,
youtube-transcript-api 1.2.5, FFmpeg 6.1.1.

| Check | Result |
|-------|--------|
| `python -m pytest` | **91 passed** (~32 s) |
| Parity vs. original code: the original pure functions (time format, URL parsing, chunking, evidence check, clip validation/scoring, de-duplication, region/crop, all layout filter strings, render-row validation) were extracted from the old `app.py` and compared with the new modules on 2,147 generated inputs | **0 mismatches** |
| Every module imports on its own (no circular imports) | pass |
| Layering: no lower layer imports Streamlit or `ui`; `ai` and `rendering` don't import each other | pass |
| No hardcoded machine paths | pass |
| Real `streamlit run app.py --server.headless true`: `/_stcore/health` and `/` | HTTP 200 / 200 |

Test coverage by file: transcript (24: URL parsing, formatting, chunking, mocked caption
fetch), AI validation/dedup (10), analyzer (6), Ollama client against a fake local HTTP
server (9), rendering (32: region/layout validation and **real FFmpeg renders of all four
layouts**, checking 1080×1920 output, audio present, correct duration, and failure cases),
UI via Streamlit's headless `AppTest` (5: startup, bad URL, full extract→analyze flow with
fakes, layout validation, AI failure), config/utils (5).

### What was NOT verified (please check on your machine)

- **PowerShell scripts were not executed.** The sandbox has no Windows or PowerShell.
  They are short and were written carefully, but treat them as untested; the manual
  commands in the README are equivalent.
- **No live YouTube request and no real Ollama model** were used (no suitable access here).
  The caption library and Ollama are exercised through mocks / a fake HTTP server shaped
  like their real responses. The prompts and validation are unchanged, but real-model answer quality was not measured.
- **The browser upload → render click-through** was not exercised, because Streamlit's test
  harness can't upload files. The two halves are covered separately: render logic with
  real FFmpeg, and button/state logic with `AppTest`.
- Tested on Python 3.12, not on your Python 3.14.

## Incomplete features / known limitations

- No audio transcription: videos without captions can't be analyzed.
- No video-frame or audio analysis (silent visual highlights, loudness, scene changes). No
  such code existed, so no empty package was created; the architecture doc says where it fits.
- No automatic webcam detection; facecam/gameplay regions are set with sliders and there is
  no visual crop preview.
- Caption language choices are limited to `en`, `en-US`, `en-GB` (as before).
- Rendering is sequential and CPU-only (`libx264`); output is returned as one ZIP in memory.
- A single local model is used; there is no result caching, so re-running analysis repeats all model calls.
