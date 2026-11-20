# ClipForge AI

ClipForge AI turns YouTube VODs and live streams into vertical `1080×1920` short-form videos (streamer webcam on top, gameplay on bottom) using Streamlit, `yt-dlp`, FFmpeg, OpenCV, and local AI via Ollama.

---

## Prerequisites

1. **Python virtual environment (`.venv`)** with project dependencies installed.
2. **OpenCV 4.x (`opencv-python<5`)** so `cv2.CascadeClassifier` and Haar cascades load properly.
3. **FFmpeg & `ffplay` / VLC** available on your system `PATH` (or configured in settings).
4. **`yt-dlp`** installed in `.venv` and kept up to date (`python -m pip install -U yt-dlp`).
5. **Ollama** (optional / for transcript clip analysis): running locally with your configured model (e.g., Qwen).

---

## How to Start Everything & Run

### 1. Open Terminal in the Project Root and Activate `.venv`
```powershell
cd C:\Users\anish\Downloads\clipforge_ai_facecam_gameplay_hq\clipforge_ai
.\.venv\Scripts\Activate.ps1
```

### 2. Verify Key Tools (First-Time / Sanity Check)
```powershell
python -m pip install -U yt-dlp "opencv-python<5"
python -c "import cv2; c = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'); print('OpenCV Cascade OK:', not c.empty())"
ffmpeg -version
```

### 3. Start Ollama (If Using AI Clip Moment Detection)
```powershell
ollama serve
```
*(In a separate terminal if needed, ensure your model is pulled, e.g., `ollama pull qwen2.5` or your configured model.)*

### 4. Start the ClipForge AI App
```powershell
streamlit run app.py
```
Once Streamlit launches, open the local URL shown in the terminal (typically `http://localhost:8501`).

---

## How to Use the Main Workflows

### A. Static VOD Clips (Transcript + AI Moments)
1. Paste a **YouTube video URL** and click **1. Extract transcript**.
2. Click **2. Find clip moments** to analyze transcript chunks via Ollama.
3. Review/edit clips and render vertical outputs.

### B. Live Stream Interval Shots
1. Paste an active **Live YouTube stream URL**.
2. Choose **Every how many minutes (1–10)**, **Short video length (up to 60s)**, and **Total number of videos**.
3. Optionally click **Grab full live frame** or **Auto-detect face (seed box)** and fine-tune the streamer box (`X`, `Y`, `Width`, `Height` or corner presets).
4. Click **Start live interval shot capture & render** to generate and auto-save the `.zip` archive in `outputs/`.

### C. Live Vertical Stream Relay (`1080×1920`)
1. Paste a **Source YouTube live stream URL**.
2. Select **Output destination** (**Sample local live link (HLS)** or **Custom RTMP / RTMPS link**) and adjust **Top streamer height (%)**.
3. Use **Grab full live frame** or **Auto-detect face (seed box)** + manual sliders/presets to frame the streamer.
4. Click **Start live vertical link**.
5. Watch via the embedded preview player or open the generated link (e.g., `http://localhost:8765/live_shorts/index.m3u8`) in **VLC** or **`ffplay`**:
   ```powershell
   ffplay "http://localhost:8765/live_shorts/index.m3u8"
   ```

---

## How to Stop & Close Everything Cleanly

1. **Stop the Live Vertical Stream Relay:**
   * Click **Stop live vertical link** in the Streamlit UI so the background FFmpeg relay process terminates cleanly.
2. **Close Media Players:**
   * Close VLC, `ffplay`, or any browser tabs viewing `http://localhost:8765/live_shorts/index.m3u8`.
3. **Stop Streamlit:**
   * In the terminal running `streamlit run app.py`, press **`Ctrl + C`**.
4. **Stop Ollama (if started in a terminal):**
   * Press **`Ctrl + C`** in the `ollama serve` terminal window (or close its window).
5. **Deactivate the Python Virtual Environment (optional):**
   ```powershell
   deactivate
   ```
6. **Force-kill leftover background processes (only if a port or `ffmpeg.exe` stays stuck):**
   ```powershell
   Get-Process ffmpeg, streamlit -ErrorAction SilentlyContinue | Stop-Process -Force
   ```


==============================================================================================================================================
## Local LLM (Ollama): How to Check, Stop, Unload & Free Space

Stopping or unloading a local LLM frees **RAM, GPU VRAM, and CPU/GPU compute** (helpful while running live FFmpeg video encoding/relaying), while **disk space** is only freed if you remove stored models.

### 1. Check What Models Are Downloaded & Currently Loaded in Memory
```powershell
# List all models stored on disk
ollama list

# Check which models are currently loaded in RAM/VRAM and running
ollama ps
```

### 2. Check If Ollama Background Processes Are Running
```powershell
Get-Process ollama -ErrorAction SilentlyContinue
```

### 3. Stop / Unload the Local LLM (Free RAM / VRAM / Compute)
* **Unload a specific model from memory** (keeps Ollama installed/ready, frees RAM/VRAM):
  ```powershell
  ollama stop <model-name>
  ```
* **Stop a running `ollama serve` session:**
  * Press **`Ctrl + C`** in the terminal window running `ollama serve` (or close that terminal window).
* **Stop background Ollama processes on Windows:**
  ```powershell
  Get-Process ollama -ErrorAction SilentlyContinue | Stop-Process -Force
  ```
* **Verify it is stopped:**
  ```powershell
  Get-Process ollama -ErrorAction SilentlyContinue
  ```
  *(If stopped, this command returns nothing.)*

### 4. Reclaim Disk Space (Only If You Want to Delete a Model From Storage)
```powershell
ollama list
ollama rm <model-name>
```

==============================================================================================================================================