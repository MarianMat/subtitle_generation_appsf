import os
import re
from io import BytesIO
from pathlib import Path

import streamlit as st
from openai import OpenAI
from pydub import AudioSegment

st.set_page_config(page_title="Aplikacja Generowanie Napisów V5", page_icon="🎬", layout="wide")
st.title("🎬 Aplikacja Generowanie Napisów — V5")
st.write("Wgraj film, wyodrębnij audio, wygeneruj napisy, edytuj je i pobierz plik SRT.")

def secret(name, default=None):
    try:
        value = st.secrets.get(name)
        if value:
            return str(value)
    except Exception:
        pass
    return os.getenv(name, default)

def extract_audio(data, ext):
    audio = AudioSegment.from_file(BytesIO(data), format=ext)
    out = BytesIO()
    audio.export(out, format="mp3", bitrate="64k")
    return out.getvalue()

def split_audio(data, minutes=15):
    audio = AudioSegment.from_file(BytesIO(data), format="mp3")
    chunk_ms = minutes * 60 * 1000
    chunks = []
    for start in range(0, len(audio), chunk_ms):
        out = BytesIO()
        audio[start:start + chunk_ms].export(out, format="mp3", bitrate="64k")
        chunks.append((out.getvalue(), start / 1000))
    return chunks

def timestamp(seconds):
    ms = max(0, int(round(float(seconds) * 1000)))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, milli = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{milli:03d}"

def make_srt(segments):
    blocks = []
    for i, seg in enumerate(segments, 1):
        text = seg["text"].strip()
        if text:
            start, end = sorted((float(seg["start"]), float(seg["end"])))
            blocks.append(f"{i}\\n{timestamp(start)} --> {timestamp(end)}\\n{text}\\n")
    return "\\n".join(blocks)

def valid_srt(text):
    pattern = re.compile(r"^\\d{2}:\\d{2}:\\d{2},\\d{3}\\s*-->\\s*\\d{2}:\\d{2}:\\d{2},\\d{3}$")
    count = 0
    for block in re.split(r"\\n\\s*\\n", text.strip()):
        lines = block.strip().splitlines()
        if len(lines) >= 3 and lines[0].strip().isdigit() and pattern.match(lines[1].strip()):
            count += 1
    return count

video = st.file_uploader("Wybierz plik wideo", type=["mp4", "mov", "m4v", "webm", "avi"])
if not video:
    st.info("Wgraj film, aby rozpocząć.")
    st.stop()

video_bytes = video.getvalue()
ext = Path(video.name).suffix.lower().lstrip(".")
if ext == "m4v":
    ext = "mp4"
mime = video.type or "video/mp4"

st.subheader("1. Film")
st.video(video_bytes, format=mime)

st.subheader("2. Wyodrębnij audio")
if st.button("🎧 Wyodrębnij audio"):
    try:
        with st.spinner("Wyodrębniam audio..."):
            st.session_state["v5_audio"] = extract_audio(video_bytes, ext)
            st.session_state["v5_video_name"] = video.name
        st.success("Audio gotowe.")
    except Exception as e:
        st.error(f"Nie udało się wyodrębnić audio: {e}")

audio = st.session_state.get("v5_audio")
if not audio or st.session_state.get("v5_video_name") != video.name:
    st.stop()

st.audio(audio, format="audio/mp3")
st.caption(f"Rozmiar audio: {len(audio) / 1024 / 1024:.1f} MB")

st.subheader("3. Generowanie napisów")
api_key = secret("OPENAI_API_KEY")
model = secret("OPENAI_TRANSCRIPTION_MODEL", "whisper-1")
if not api_key:
    st.error("Brak OPENAI_API_KEY. Dodaj go w Streamlit Cloud → Manage app → Settings → Secrets.")
    st.stop()

st.caption(f"Model: {model}")
if st.button("🚀 Generuj napisy", type="primary"):
    try:
        client = OpenAI(api_key=api_key)
        chunks = split_audio(audio)
        segments = []
        progress = st.progress(0)
        for i, (chunk, offset) in enumerate(chunks, 1):
            progress.progress((i - 1) / len(chunks), text=f"Transkrypcja części {i}/{len(chunks)}...")
            file = BytesIO(chunk)
            file.name = f"audio_{i}.mp3"
            result = client.audio.transcriptions.create(
                model=model,
                file=file,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )
            for seg in (getattr(result, "segments", None) or []):
                text = str(getattr(seg, "text", "")).strip()
                if text:
                    start = float(getattr(seg, "start", 0)) + offset
                    end = float(getattr(seg, "end", start - offset)) + offset
                    segments.append({"start": start, "end": end, "text": text})
        progress.progress(1.0, text="Gotowe")
        if not segments:
            raise RuntimeError("API nie zwróciło segmentów z timestampami. Sprawdź obsługę verbose_json i timestamp_granularities przez wybrany model.")
        st.session_state["v5_srt"] = make_srt(segments)
        st.session_state["v5_srt_video_name"] = video.name
        st.success(f"Utworzono {len(segments)} segmentów.")
    except Exception as e:
        st.error(f"Błąd transkrypcji: {e}")

if st.session_state.get("v5_srt") and st.session_state.get("v5_srt_video_name") == video.name:
    st.subheader("4. Edycja SRT")
    edited = st.text_area("Treść pliku SRT", value=st.session_state["v5_srt"], height=450, key=f"srt_{video.name}")
    st.session_state["v5_srt"] = edited
    count = valid_srt(edited)
    if count:
        st.success(f"Rozpoznano {count} bloków SRT.")
        st.download_button("⬇️ Pobierz plik SRT", data=edited.encode("utf-8"), file_name=Path(video.name).stem + ".srt", mime="application/x-subrip", on_click="ignore")
        st.subheader("5. Podgląd filmu z napisami")
        try:
            st.video(video_bytes, format=mime, subtitles=edited)
        except Exception as e:
            st.warning(f"Podgląd napisów jest niedostępny, ale możesz pobrać SRT. Szczegóły: {e}")
    else:
        st.warning("Nie rozpoznano bloków SRT. Zachowaj numer, wiersz czasu i pusty wiersz między blokami.")
