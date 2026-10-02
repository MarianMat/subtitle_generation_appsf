import os
import re
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

# ---------------------------------------------------------------------------
# Konfiguracja
# ---------------------------------------------------------------------------

load_dotenv()

st.set_page_config(
    page_title="Generator napisów V5",
    page_icon="🎬",
    layout="wide",
)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY", "")
OPENAI_TRANSCRIPTION_MODEL = (
    os.getenv("OPENAI_TRANSCRIPTION_MODEL")
    or st.secrets.get("OPENAI_TRANSCRIPTION_MODEL", "whisper-1")
)

if not OPENAI_API_KEY:
    st.error("Brak klucza OPENAI_API_KEY. Dodaj go w Secrets lub w pliku .env.")
    st.stop()

client = OpenAI(api_key=OPENAI_API_KEY)

WORK_DIR = Path(tempfile.gettempdir()) / "subtitle_v5"
WORK_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# FFmpeg / ffprobe – bez pydub
# ---------------------------------------------------------------------------

def _require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        st.error(
            f"Nie znaleziono `{name}` w systemie. "
            f"Dodaj `ffmpeg` do packages.txt (Streamlit Cloud) "
            f"lub zainstaluj lokalnie."
        )
        st.stop()
    return path


def get_duration(path: str) -> float:
    """Zwraca długość pliku multimedialnego w sekundach."""
    ffprobe = _require_binary("ffprobe")
    result = subprocess.run(
        [
            ffprobe, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def extract_audio(video_path: str, audio_path: str,
                  sample_rate: int = 16000, channels: int = 1) -> None:
    """Wyciąga audio z wideo do pliku WAV (mono, 16 kHz)."""
    ffmpeg = _require_binary("ffmpeg")
    subprocess.run(
        [
            ffmpeg, "-y",
            "-i", video_path,
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", str(sample_rate),
            "-ac", str(channels),
            audio_path,
        ],
        capture_output=True, text=True, check=True,
    )


def split_audio(audio_path: str, out_dir: str, segment_seconds: int = 600):
    """Dzieli audio na segmenty. Zwraca listę ścieżek."""
    ffmpeg = _require_binary("ffmpeg")
    pattern = os.path.join(out_dir, "chunk_%03d.wav")
    subprocess.run(
        [
            ffmpeg, "-y",
            "-i", audio_path,
            "-f", "segment",
            "-segment_time", str(segment_seconds),
            "-c", "copy",
            pattern,
        ],
        capture_output=True, text=True, check=True,
    )
    chunks = sorted(Path(out_dir).glob("chunk_*.wav"))
    return [str(p) for p in chunks]


def has_audio_stream(path: str) -> bool:
    ffprobe = _require_binary("ffprobe")
    result = subprocess.run(
        [
            ffprobe, "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=index",
            "-of", "csv=p=0",
            path,
        ],
        capture_output=True, text=True,
    )
    return bool(result.stdout.strip())


# ---------------------------------------------------------------------------
# Transkrypcja (OpenAI)
# ---------------------------------------------------------------------------

def transcribe_chunk(chunk_path: str, offset_seconds: float = 0.0):
    """
    Transkrybuje pojedynczy plik audio.
    Zwraca listę segmentów: [{"start": float, "end": float, "text": str}, ...]
    """
    with open(chunk_path, "rb") as f:
        response = client.audio.transcriptions.create(
            model=OPENAI_TRANSCRIPTION_MODEL,
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )

    segments = []
    raw_segments = getattr(response, "segments", None) or []
    for seg in raw_segments:
        start = float(getattr(seg, "start", 0.0)) + offset_seconds
        end = float(getattr(seg, "end", 0.0)) + offset_seconds
        text = (getattr(seg, "text", "") or "").strip()
        if text:
            segments.append({"start": start, "end": end, "text": text})

    # Fallback – brak segmentów, ale jest pełny tekst
    if not segments:
        full_text = (getattr(response, "text", "") or "").strip()
        if full_text:
            segments.append({
                "start": offset_seconds,
                "end": offset_seconds + 5.0,
                "text": full_text,
            })
    return segments


def transcribe_audio_in_chunks(chunks, progress_cb=None):
    all_segments = []
    current_offset = 0.0
    total = len(chunks)

    for i, chunk in enumerate(chunks, start=1):
        if progress_cb:
            progress_cb(i, total, chunk)
        segs = transcribe_chunk(chunk, offset_seconds=current_offset)
        all_segments.extend(segs)
        try:
            current_offset += get_duration(chunk)
        except Exception:
            current_offset += 600.0  # bezpieczny fallback

    return all_segments


# ---------------------------------------------------------------------------
# SRT
# ---------------------------------------------------------------------------

def format_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    ms = int(round(seconds * 1000))
    h = ms // 3_600_000
    ms %= 3_600_000
    m = ms // 60_000
    ms %= 60_000
    s = ms // 1000
    ms %= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def segments_to_srt(segments) -> str:
    lines = []
    for i, seg in enumerate(segments, start=1):
        lines.append(str(i))
        lines.append(
            f"{format_timestamp(seg['start'])} --> {format_timestamp(seg['end'])}"
        )
        lines.append(seg["text"])
        lines.append("")
    return "\n".join(lines)


def parse_srt(srt_text: str):
    blocks = re.split(r"\n\s*\n", srt_text.strip())
    segments = []
    time_re = re.compile(
        r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*"
        r"(\d{2}):(\d{2}):(\d{2}),(\d{3})"
    )

    def to_sec(h, m, s, ms):
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 2:
            continue
        time_line = None
        text_start = 1
        for idx, line in enumerate(lines):
            if "-->" in line:
                time_line = line
                text_start = idx + 1
                break
        if not time_line:
            continue
        match = time_re.search(time_line)
        if not match:
            continue
        g = match.groups()
        start = to_sec(*g[:4])
        end = to_sec(*g[4:])
        text = "\n".join(lines[text_start:]).strip()
        segments.append({"start": start, "end": end, "text": text})
    return segments


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

st.title("🎬 Generator napisów V5")
st.caption("FFmpeg + OpenAI Whisper · wersja samodzielna, bez pydub")

with st.sidebar:
    st.header("Ustawienia")
    st.write(f"**Model transkrypcji:** `{OPENAI_TRANSCRIPTION_MODEL}`")
    segment_seconds = st.slider(
        "Długość segmentu audio (s)", min_value=60, max_value=1200,
        value=600, step=60,
    )
    st.markdown("---")
    st.markdown(
        "**Wskazówka:** dla długich filmów transkrypcja może trwać kilka minut."
    )

uploaded = st.file_uploader(
    "Wgraj film lub audio",
    type=["mp4", "mov", "mkv", "avi", "webm", "mp3", "wav", "m4a", "flac"],
)

if uploaded is not None:
    session_dir = WORK_DIR / "session"
    if session_dir.exists():
        shutil.rmtree(session_dir, ignore_errors=True)
    session_dir.mkdir(parents=True, exist_ok=True)

    input_path = session_dir / uploaded.name
    with open(input_path, "wb") as f:
        f.write(uploaded.getbuffer())

    st.success(f"Wgrano: {uploaded.name}")

    is_video = uploaded.type and uploaded.type.startswith("video")
    if is_video:
        st.video(str(input_path))

    if st.button("▶️ Generuj napisy", type="primary"):
        try:
            with st.spinner("Analiza pliku..."):
                if not has_audio_stream(str(input_path)):
                    st.error("Plik nie zawiera ścieżki audio.")
                    st.stop()

            audio_path = session_dir / "audio.wav"

            with st.spinner("Wyodrębnianie audio (FFmpeg)..."):
                extract_audio(str(input_path), str(audio_path))

            with st.spinner("Dzielenie audio na segmenty..."):
                chunks_dir = session_dir / "chunks"
                chunks_dir.mkdir(exist_ok=True)
                chunks = split_audio(
                    str(audio_path), str(chunks_dir), segment_seconds
                )

            st.info(f"Liczba segmentów: {len(chunks)}")

            progress = st.progress(0.0, text="Transkrypcja...")

            def cb(i, total, chunk):
                progress.progress(
                    i / total, text=f"Transkrypcja {i}/{total}: {Path(chunk).name}"
                )

            with st.spinner("Transkrypcja (OpenAI Whisper)..."):
                segments = transcribe_audio_in_chunks(chunks, progress_cb=cb)

            progress.empty()

            if not segments:
                st.error("Nie udało się uzyskać transkrypcji.")
                st.stop()

            srt_text = segments_to_srt(segments)
            st.session_state["srt_text"] = srt_text
            st.session_state["segments"] = segments
            st.success(f"Gotowe! Segmentów: {len(segments)}")

        except subprocess.CalledProcessError as e:
            st.error("Błąd FFmpeg.")
            st.code((e.stderr or "")[-2000:])
        except Exception as e:
            st.exception(e)

# --- Edycja i podgląd napisów ------------------------------------------------

if "srt_text" in st.session_state:
    st.markdown("---")
    st.subheader("✏️ Edycja napisów (SRT)")
    edited_srt = st.text_area(
        "Możesz poprawić napisy ręcznie:",
        value=st.session_state["srt_text"],
        height=400,
    )

    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            "⬇️ Pobierz .srt",
            data=edited_srt.encode("utf-8"),
            file_name="napisy.srt",
            mime="text/plain",
        )
    with col2:
        st.download_button(
            "⬇️ Pobierz .txt",
            data="\n".join(
                s["text"] for s in parse_srt(edited_srt)
            ).encode("utf-8"),
            file_name="napisy.txt",
            mime="text/plain",
        )

    # Podgląd wideo z napisami (jeśli wgrany plik był wideo)
    st.markdown("---")
    st.subheader("👀 Podgląd")
    if uploaded is not None and uploaded.type and uploaded.type.startswith("video"):
        st.video(str(input_path), subtitles=edited_srt.encode("utf-8"))
    else:
        st.caption("Podgląd wideo dostępny tylko dla plików wideo.")
