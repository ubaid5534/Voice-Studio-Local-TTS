"""Voice Studio: local-first browser UI for Edge and offline Piper TTS.

Run with: python -m uvicorn app:app --host 127.0.0.1 --port 8765
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import time
import uuid
import wave
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("VOICE_STUDIO_DATA_DIR", str(ROOT / "data"))).resolve()
MODELS = DATA / "models"
OUTPUT = DATA / "audio"
CATALOG_CACHE = DATA / "piper_catalog.json"
STATIC = ROOT / "static"
for directory in (DATA, MODELS, OUTPUT):
    directory.mkdir(parents=True, exist_ok=True)

PIPER_CATALOG_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/voices.json"
PIPER_MODEL_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
MAX_TEXT = 12000
EDGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{3,100}$")
AUDIO_ID = re.compile(r"^[a-f0-9]{32}\.(mp3|wav)$")
MODEL_ID = re.compile(r"^[A-Za-z]{2,3}_[A-Za-z]{2,3}-[A-Za-z0-9_-]+-(x_low|low|medium|high)$")

# Safety-net catalog for the first launch without access to the remote index.
# Real catalog fetched from rhasspy/piper-voices includes many more languages and models.
STARTER = {
    "en_US-amy-medium": ("amy", "English", "United States", "Female", "en/en_US/amy/medium"),
    "en_US-joe-medium": ("joe", "English", "United States", "Male", "en/en_US/joe/medium"),
    "en_US-hfc_female-medium": ("hfc_female", "English", "United States", "Female", "en/en_US/hfc_female/medium"),
    "en_US-hfc_male-medium": ("hfc_male", "English", "United States", "Male", "en/en_US/hfc_male/medium"),
    "en_GB-northern_english_male-medium": ("northern_english_male", "English", "Great Britain", "Male", "en/en_GB/northern_english_male/medium"),
    "en_GB-southern_english_female-low": ("southern_english_female", "English", "Great Britain", "Female", "en/en_GB/southern_english_female/low"),
}


def starter_catalog() -> dict:
    output = {}
    for key, (name, lang, country, _gender, folder) in STARTER.items():
        output[key] = {
            "key": key,
            "name": name,
            "language": {"code": key.split("-")[0], "name_english": lang, "country_english": country},
            "quality": key.rsplit("-", 1)[-1],
            "num_speakers": 1,
            "speaker_id_map": {},
            "files": {f"{folder}/{key}.onnx": {}, f"{folder}/{key}.onnx.json": {}},
        }
    return output


def fetch_catalog(refresh: bool = False) -> dict:
    if CATALOG_CACHE.is_file() and not refresh:
        try:
            cached = json.loads(CATALOG_CACHE.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and len(cached) > 10:
                return cached
        except (OSError, ValueError):
            pass
    try:
        req = Request(PIPER_CATALOG_URL, headers={"User-Agent": "VoiceStudio/1.0"})
        with urlopen(req, timeout=9) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("Voice catalog too large")
        catalog = json.loads(raw)
        if not isinstance(catalog, dict) or len(catalog) < 20:
            raise ValueError("Invalid voice catalog")
        tmp = CATALOG_CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
        tmp.replace(CATALOG_CACHE)
        return catalog
    except Exception:
        if CATALOG_CACHE.is_file():
            try:
                return json.loads(CATALOG_CACHE.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        return starter_catalog()


def model_paths(key: str) -> tuple[Path, Path]:
    return MODELS / f"{key}.onnx", MODELS / f"{key}.onnx.json"


def is_installed(key: str) -> bool:
    onnx, config = model_paths(key)
    return onnx.is_file() and onnx.stat().st_size > 10_000 and config.is_file()


def get_gender(name: str, key: str, speaker_name: str = "") -> str:
    text = f"{speaker_name} {name}".lower()
    if "female" in text:
        return "Female"
    if "male" in text:
        return "Male"
    lookup = {"en_US-amy-medium": "Female", "en_US-joe-medium": "Male",
              "en_US-lessac-medium": "Female"}
    return lookup.get(key, "Unspecified")


def normalize_piper(catalog: dict) -> list[dict]:
    voices = []
    for key, entry in catalog.items():
        if not MODEL_ID.fullmatch(key) or not isinstance(entry, dict):
            continue
        language = entry.get("language") or {}
        if not isinstance(language, dict):
            continue
        speaker_map = entry.get("speaker_id_map") or {}
        if not isinstance(speaker_map, dict):
            speaker_map = {}
        entries = list(speaker_map.items()) if speaker_map else [(None, None)]
        for speaker_name, speaker_id in entries:
            if speaker_id is not None and (not isinstance(speaker_id, int) or speaker_id < 0):
                continue
            name = str(entry.get("name", key))
            pretty = name.replace("_", " ").replace("-", " ").title()
            if speaker_name:
                pretty += f" · {str(speaker_name).replace('_', ' ').title()}"
            code = str(language.get("code", key.split("-")[0])).replace("_", "-")
            lang = str(language.get("name_english", code))
            country = str(language.get("country_english", ""))
            voices.append({
                "id": key + (f"::{speaker_id}" if speaker_id is not None else ""),
                "key": key, "name": pretty,
                "gender": get_gender(name, key, str(speaker_name or "")),
                "locale": code, "language": lang, "country": country,
                "quality": str(entry.get("quality", "")), "installed": is_installed(key),
                "speaker_id": speaker_id, "engine": "piper",
            })
    return sorted(voices, key=lambda v: (not v["installed"], v["language"], v["country"], v["name"]))


def normalize_edge(voices: list[dict]) -> list[dict]:
    result = []
    for voice in voices:
        short = str(voice.get("ShortName", ""))
        if not EDGE_ID.fullmatch(short):
            continue
        locale = str(voice.get("Locale", short.rsplit("-", 1)[0]))
        gender = str(voice.get("Gender", "Unspecified")).capitalize()
        if gender not in ("Male", "Female"):
            gender = "Unspecified"
        friendly = str(voice.get("FriendlyName") or short.split("-")[-1].replace("Neural", ""))
        display = short.split("-")[-1].replace("Neural", "")
        result.append({"id": short, "key": short, "name": display, "friendly_name": friendly,
                       "gender": gender, "locale": locale, "language": locale.split("-")[0].upper(),
                       "country": locale, "quality": "Neural", "installed": True,
                       "speaker_id": None, "engine": "edge"})
    return sorted(result, key=lambda v: (v["locale"], v["name"]))


def _verified_catalog_file(entry: dict, suffix: str) -> tuple[str, int | None]:
    for path, info in (entry.get("files") or {}).items():
        if not isinstance(path, str) or not path.endswith(suffix) or not isinstance(info, dict):
            continue
        parts = path.split("/")
        if any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) or part in (".", "..") for part in parts):
            continue
        size = info.get("size_bytes")
        if size is not None and (not isinstance(size, int) or size <= 0 or size > 400_000_000):
            continue
        return path, size
    raise ValueError("Model file not found in catalog")


def download_model(key: str) -> bool:
    if not MODEL_ID.fullmatch(key):
        raise ValueError("Invalid voice ID")
    catalog = fetch_catalog()
    entry = catalog.get(key)
    if not isinstance(entry, dict):
        raise ValueError("Unknown voice ID")
    if is_installed(key):
        return True
    targets = model_paths(key)
    files = [_verified_catalog_file(entry, ".onnx"), _verified_catalog_file(entry, ".onnx.json")]
    for (relative, expected_size), target in zip(files, targets):
        if target.is_file() and target.stat().st_size > 0:
            if expected_size is None or target.stat().st_size == expected_size:
                continue
        url = PIPER_MODEL_BASE + quote(relative, safe="/")
        temp = target.with_suffix(target.suffix + ".part")
        try:
            with urlopen(Request(url, headers={"User-Agent": "VoiceStudio/1.0"}), timeout=90) as response, temp.open("wb") as out:
                total = 0
                while True:
                    block = response.read(1024 * 512)
                    if not block:
                        break
                    total += len(block)
                    if total > 400_000_000 or (expected_size is not None and total > expected_size):
                        raise ValueError("Downloaded model is larger than expected")
                    out.write(block)
            if expected_size is not None and total != expected_size:
                raise ValueError("Downloaded model size did not match catalog")
            if total == 0:
                raise ValueError("Empty model file")
            temp.replace(target)
        finally:
            temp.unlink(missing_ok=True)
    return is_installed(key)


def synthesize_piper(text: str, voice_id: str, rate: int, target: Path) -> None:
    try:
        from piper import PiperVoice, SynthesisConfig
    except ImportError as exc:
        raise RuntimeError("Offline engine not installed. Run the setup_offline script.") from exc
    parts = voice_id.split("::", 1)
    key = parts[0]
    if not MODEL_ID.fullmatch(key) or key not in fetch_catalog():
        raise ValueError("Unknown Piper voice")
    if not is_installed(key):
        raise RuntimeError("Download this voice model first to use it offline.")
    config = json.loads(model_paths(key)[1].read_text(encoding="utf-8"))
    speaker_count = int(config.get("num_speakers", 1))
    speaker_id = int(parts[1]) if len(parts) == 2 else None
    if speaker_id is not None and not (0 <= speaker_id < speaker_count):
        raise ValueError("Invalid speaker ID")
    piper_voice = PiperVoice.load(str(model_paths(key)[0]))
    settings = SynthesisConfig(speaker_id=speaker_id, length_scale=round(1.0 / (1 + rate / 100), 3))
    with wave.open(str(target), "wb") as wav:
        piper_voice.synthesize_wav(text, wav, syn_config=settings)


def convert_audio(source: Path, fmt: str) -> Path:
    if source.suffix == "." + fmt:
        return source
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("Install FFmpeg to convert audio formats, or select the native format.")
    target = source.with_suffix("." + fmt)
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source)]
    args += (["-codec:a", "libmp3lame", "-qscale:a", "3"] if fmt == "mp3" else ["-codec:a", "pcm_s16le"])
    args.append(str(target))
    try:
        subprocess.run(args, check=True, capture_output=True, timeout=90)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        target.unlink(missing_ok=True)
        raise RuntimeError("Audio conversion failed") from exc
    source.unlink(missing_ok=True)
    return target


def get_history() -> list[dict]:
    records = []
    for path in OUTPUT.glob("*.json"):
        if not re.fullmatch(r"[a-f0-9]{32}\.json", path.name):
            continue
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            audio = OUTPUT / item["filename"]
            if audio.exists():
                records.append(item)
        except (KeyError, ValueError, OSError):
            continue
    return sorted(records, key=lambda x: x.get("created", 0), reverse=True)[:30]


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    voice_id: str = Field(min_length=3, max_length=125)
    engine: str = Field(pattern=r"^(edge|piper)$")
    rate: int = Field(default=0, ge=-50, le=50)
    pitch: int = Field(default=0, ge=-50, le=50)
    output_format: str = Field(default="auto", pattern=r"^(auto|mp3|wav)$")
    preview: bool = False


class ModelRequest(BaseModel):
    key: str


app = FastAPI(title="Voice Studio", docs_url=None, redoc_url=None)


@app.get("/api/status")
def status():
    try:
        import edge_tts  # noqa: F401
        edge_ready = True
    except ImportError:
        edge_ready = False
    try:
        import piper  # noqa: F401
        piper_ready = True
    except ImportError:
        piper_ready = False
    return {"edge_installed": edge_ready, "piper_installed": piper_ready,
            "ffmpeg": bool(shutil.which("ffmpeg")), "local_only": True,
            "stored_models": len(list(MODELS.glob("*.onnx")))}


@app.get("/api/voices")
async def voices(engine: str = "edge", refresh: bool = False):
    if engine == "piper":
        catalog = await run_in_threadpool(fetch_catalog, refresh)
        result = normalize_piper(catalog)
        return {"voices": result, "count": len(result), "catalog_cached": CATALOG_CACHE.is_file()}
    if engine != "edge":
        raise HTTPException(400, "Unknown engine")
    try:
        import edge_tts
    except ImportError:
        raise HTTPException(503, "Edge engine not installed. Run the setup script.")
    try:
        result = normalize_edge(await edge_tts.list_voices())
    except Exception as exc:
        raise HTTPException(503, "Could not load cloud voices. Check internet and retry.") from exc
    return {"voices": result, "count": len(result), "catalog_cached": False}


@app.post("/api/install-voice")
async def install_voice(request: ModelRequest):
    if not MODEL_ID.fullmatch(request.key):
        raise HTTPException(400, "Invalid voice ID")
    try:
        installed = await run_in_threadpool(download_model, request.key)
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, "Voice download failed. Check internet connection and available disk space.") from exc
    if not installed:
        raise HTTPException(502, "Voice files were not installed completely")
    return {"installed": True, "key": request.key}


@app.post("/api/synthesize")
async def synthesize(payload: SpeakRequest):
    text = payload.text.strip()
    if not text:
        raise HTTPException(400, "Please enter text")
    if payload.preview:
        text = text[:220].rsplit(" ", 1)[0] or text[:220]
    base = uuid.uuid4().hex
    extension = "mp3" if payload.engine == "edge" else "wav"
    target = OUTPUT / f"{base}.{extension}"
    try:
        if payload.engine == "edge":
            if not EDGE_ID.fullmatch(payload.voice_id):
                raise ValueError("Invalid cloud voice")
            try:
                import edge_tts
            except ImportError as exc:
                raise RuntimeError("Edge voice engine is not installed") from exc
            synth = edge_tts.Communicate(text, voice=payload.voice_id,
                                        rate=f"{payload.rate:+d}%", pitch=f"{payload.pitch:+d}Hz")
            await synth.save(str(target))
        else:
            await run_in_threadpool(synthesize_piper, text, payload.voice_id, payload.rate, target)
        if not target.exists() or target.stat().st_size == 0:
            raise RuntimeError("The voice engine returned no audio")
        fmt = payload.output_format if payload.output_format != "auto" else extension
        if fmt != extension:
            target = await run_in_threadpool(convert_audio, target, fmt)
    except (ValueError, RuntimeError) as exc:
        for file in OUTPUT.glob(f"{base}.*"):
            file.unlink(missing_ok=True)
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        for file in OUTPUT.glob(f"{base}.*"):
            file.unlink(missing_ok=True)
        raise HTTPException(502, "Speech generation failed. Check the voice engine or network.") from exc
    record = {"filename": target.name, "engine": payload.engine,
              "voice_id": payload.voice_id, "text": text[:160],
              "chars": len(text), "created": time.time(), "format": fmt,
              "url": f"/api/audio/{target.name}"}
    (OUTPUT / f"{base}.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return record


@app.get("/api/history")
def history():
    return {"items": get_history()}


@app.get("/api/audio/{filename}")
def audio(filename: str):
    if not AUDIO_ID.fullmatch(filename):
        raise HTTPException(404, "Audio not found")
    path = OUTPUT / filename
    if not path.exists():
        raise HTTPException(404, "Audio not found")
    mime = "audio/mpeg" if filename.endswith("mp3") else "audio/wav"
    return FileResponse(path, media_type=mime, filename=filename)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
