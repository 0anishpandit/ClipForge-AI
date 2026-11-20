# ClipForge AI

A local Windows-friendly app that finds short-form clip moments in a YouTube video's
captions using a **local Ollama model**, then cuts them from your own copy of the video
into vertical 1080×1920 MP4s with **FFmpeg**.

1. Paste a YouTube URL and extract its captions (no video is downloaded).
2. A local model proposes highlight moments; each one is checked against the transcript.
3. Review and edit the timestamps in a table.
4. Upload the original video you own, choose a vertical layout, and render.

Nothing leaves your machine except the caption request to YouTube. No API key is needed.

## Requirements

| Tool | Notes |
|------|-------|
| Python 3.10+ | Developed and tested on 3.12. Tick **Add Python to PATH** when installing. |
| FFmpeg | Needed only for rendering. Add its `bin` folder to PATH, or set `CLIPFORGE_FFMPEG`. |
| Ollama | Needed only for AI analysis. <https://ollama.com/download>, then `ollama pull qwen2.5:3b`. |

## Install (Windows PowerShell)

From the project root (the folder containing `app.py`):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

This creates `.venv`, installs `requirements.txt`, and warns if FFmpeg or Ollama are missing.
Add `-Dev` to also install the test tools.

Manual equivalent:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run.ps1
```

or, without the script: `.venv\Scripts\python.exe -m streamlit run app.py`.
The app opens at <http://localhost:8501>. (On macOS/Linux: `python -m streamlit run app.py`.)

## Using it

1. Paste a `youtube.com/watch`, `youtu.be`, `/shorts/`, `/live/` or `/embed/` URL → **Extract transcript**.
2. Make sure Ollama is running (sidebar → **Check local AI connection**) → **Find clip moments**.
3. Edit start/end seconds or titles in the table if needed.
4. Upload the source video (mp4/mov/mkv/webm, up to 2 GB), pick a layout, and **Render**.
5. Download the ZIP of finished clips.

Layouts: *Facecam + gameplay* (automatic default — streamer facecam on top, gameplay below),
*Floating facecam* (webcam overlay in the corner), *Blurred background*, and *Full-screen crop*.
Automatic mode detects the streamer's facecam region and renders in high-quality 1080×1920
(`lanczos` scaling, soft blurred facecam fill, `libx264` CRF 16, `slow` preset, 256k AAC audio),
while Manual mode lets you adjust crop percentages directly or toggle auto-detection.

## Configuration

Everything works with defaults. To change anything, copy `.env.example` to `.env`
(or set environment variables). See that file for all `CLIPFORGE_*` options:
Ollama URL/model/timeout, FFmpeg path, log level.

## Tests

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -Dev
.venv\Scripts\python.exe -m pytest
```

Tests need no network and no Ollama (a fake local server is used). FFmpeg-based tests are
skipped automatically if FFmpeg/ffprobe are not installed.

## Troubleshooting

- **"Ollama is not running"** – start the Ollama app, or run `ollama serve`.
- **"FFmpeg was not found"** – run `ffmpeg -version` in a new PowerShell window; if it fails, fix PATH or set `CLIPFORGE_FFMPEG=C:\ffmpeg\bin\ffmpeg.exe` in `.env`.
- **Transcript extraction fails** – the video may have no captions, or YouTube is blocking automated requests. Try another video later.
- **Analysis finds nothing** – the transcript may lack clear highlights; try a larger Ollama model.
- **"running scripts is disabled"** – use the `-ExecutionPolicy Bypass` form shown above.

## Limitations

- Needs existing YouTube captions; it does not transcribe audio.
- Transcript analysis cannot find silent visual highlights (no video/audio analysis yet).
- Automatic facecam detection uses OpenCV Haar cascades across sampled frames and falls back to a safe default crop if no face is detected.
- It does not download videos. Only render footage you own or are authorized to edit, and follow YouTube's terms.

More detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [docs/CHANGES_AND_VERIFICATION.md](docs/CHANGES_AND_VERIFICATION.md)
