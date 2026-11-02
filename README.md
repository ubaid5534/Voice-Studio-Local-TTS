# Voice Studio — Local Text to Speech

Voice Studio is a self-hosted browser app for producing voiceovers from text. The app runs **on your own computer** at `http://127.0.0.1:8765` and creates audio files locally. It has two speech engines:

| Engine | Voices | Internet | Output |
|---|---|---|---|
| **Neural Cloud (Edge TTS)** | A large multilingual catalog including labeled male and female voices | Required each time you generate audio | MP3 |
| **Fully Offline (Piper)** | Downloadable voice packs in many languages; some packs have several speakers | Required for first model download **only** | WAV |

When [FFmpeg](https://ffmpeg.org/download.html) is installed and on your `PATH`, you can also convert MP3 to WAV or WAV to MP3 by selecting the desired export format. Piper model files are **not bundled** with this ZIP; download the voices you want from inside the application.

## Quick start — Windows

1. Install [Python 3.11 or later](https://www.python.org/downloads/) and tick **Add Python to PATH** during installation (the Python launcher `py` is also supported).
2. Extract this ZIP to a folder you own (not inside a ZIP preview).
3. Double-click **`run_windows.bat`** to create a Python environment, install the online speech engine, and start the app. The first launch requires internet to install the Python dependencies.
4. Open **http://127.0.0.1:8765** in your browser if it does not open automatically.
5. For offline voices, double-click **`setup_offline_windows.bat`** once, restart Voice Studio if it is running, switch to **Fully Offline**, and click **Get voice** for each voice model you want.

## Quick start — macOS / Linux

Install Python 3.11+ (on macOS, [python.org](https://www.python.org/downloads/) or Homebrew). In Terminal:

```bash
cd /path/to/voice_studio
bash run_mac_linux.sh
```

Alternatively, on macOS you can double-click **`run_mac.command`** in Finder (if macOS blocks an untrusted downloaded script, launch it via Terminal instead).

Open **http://127.0.0.1:8765** in your browser. For offline speech, in another Terminal, use:

```bash
cd /path/to/voice_studio
bash setup_offline_mac_linux.sh
```

Then restart the app, choose **Fully Offline**, download a voice, and generate speech.

Note: Piper provides prebuilt packages for mainstream Windows 64-bit, Linux x86-64/ARM64 and macOS Intel/Apple Silicon. A Python installation from an unusual architecture may require additional setup.

## Using it

1. Enter or paste text in the script box (up to 12,000 characters).
2. Choose either **Neural Cloud** (online) or **Fully Offline** (Piper).
3. Search by name or language and filter **Female** / **Male**. Gender is displayed as “Voice” when the source's metadata does not specify it.
4. Pick a voice. In offline mode, first click **Get voice** and wait for the model download to finish. Voice packs can be tens or hundreds of megabytes.
5. Adjust speed. Cloud mode also supports pitch. For offline Piper the model controls speech speed, but not independent pitch in this interface.
6. Click **Listen to voice preview** or **Generate speech**. Play your audio, then click **Download audio**.
7. Recent clips stay on your machine; the app keeps files and an associated record in `data/audio/`. Delete that folder's files to clear your history.

**Tip:** use Ctrl+Enter (Windows/Linux) or Cmd+Enter (macOS) to generate quickly.

## What does "local" mean?

- The *interface, server, generated files, and downloaded voice models* live on your machine. The server listens on `127.0.0.1` only, not your network.
- **Neural Cloud / Edge TTS is not offline**: the app sends the text you enter to Microsoft's online speech service via the community `edge-tts` Python package. Do not use this mode for confidential text. The community integration is unofficial and its availability can change.
- **Piper truly runs offline after setup**. The initial `pip install` and per-voice download need internet; subsequent voice generation with a model already on disk needs no online API.
- Piper's catalog comes from the `rhasspy/piper-voices` Hugging Face repository and is cached at `data/piper_catalog.json`. A small embedded set of starter voices is shown if the catalog cannot be fetched. To refresh the full voice list later, use ↻ Refresh in the voice panel.
- Individual Piper voices have **their own model licenses**. Inspect the relevant model card in the [Piper voice repository](https://huggingface.co/rhasspy/piper-voices) before commercial distribution. The Piper runtime package itself is GPL-3.0-or-later; see its license if distributing this app with its dependencies.
- No account, analytics, API key or cloud file storage is built into this app.

## Troubleshooting

| Issue | How to fix |
|---|---|
| `py` or `python3` not found | Install Python 3.11+ and relaunch your terminal. |
| Cloud voices fail to load | Check internet access; test that your firewall allows Edge speech traffic, then refresh. |
| Piper says "engine not installed" | Run `setup_offline_*`, restart the local app. |
| Piper voice is not downloaded | Click **Get voice** for that voice; voice models are separate from the app. |
| Model download fails | Check internet, free disk space, proxy/firewall, then retry. Partial `.part` downloads are removed automatically. |
| MP3/WAV conversion fails | Install FFmpeg or select **Automatic** format (Edge = MP3, Piper = WAV). |
| Address is already in use | Quit the other Voice Studio process or change port `8765` in the launcher and open the new address. |
| Need full offline startup | Complete setup and voice downloads once, and launch with `bash run_mac_linux.sh` or `run_windows.bat` while connected; subsequent launches use already-installed dependencies in `.venv`. If fully disconnected, use `.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8765` on macOS/Linux or `.venv\\Scripts\\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8765` on Windows to skip the launcher's pip check. |

### Dependencies

The main installer uses `fastapi`, `uvicorn`, and `edge-tts`. Offline support additionally uses `piper-tts`, including the ONNX runtime it installs. FFmpeg is optional.

### Developer commands

```bash
python -m pip install -r requirements.txt
python -m pip install pytest httpx
python -m pytest -q tests
python -m uvicorn app:app --host 127.0.0.1 --port 8765
```

The test suite uses mocked voice engines and does **not** require the live Microsoft service or large Piper models. Smoke-test live speech generation on your own computer after installation.
