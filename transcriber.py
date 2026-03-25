import os
import streamlit as st
from openai import OpenAI
from pydub import AudioSegment
import tempfile


def _get_api_key():
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        try:
            key = st.secrets.get("OPENAI_API_KEY")
        except Exception:
            pass
    return key


def _get_client():
    key = _get_api_key()
    if not key:
        return None
    return OpenAI(api_key=key)


MAX_FILE_SIZE_MB = 25
CHUNK_DURATION_MS = 10 * 60 * 1000


def transcribe_audio(file_path, language=None):
    client = _get_client()
    if not client:
        return None
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    if file_size_mb <= MAX_FILE_SIZE_MB:
        return _transcribe_single(client, file_path, language)
    else:
        return _transcribe_chunked(client, file_path, language)


def _transcribe_single(client, file_path, language=None):
    try:
        with open(file_path, "rb") as audio_file:
            params = {
                "model": "whisper-1",
                "file": audio_file,
                "response_format": "text"
            }
            if language:
                params["language"] = language
            transcript = client.audio.transcriptions.create(**params)
            return transcript
    except Exception as e:
        print(f"Transcription error: {e}")
        return None


def _transcribe_chunked(client, file_path, language=None):
    try:
        audio = AudioSegment.from_file(file_path)
        chunks = [audio[i:i + CHUNK_DURATION_MS] for i in range(0, len(audio), CHUNK_DURATION_MS)]
        full_transcript = []
        for i, chunk in enumerate(chunks):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
                chunk.export(tmp.name, format="mp3")
                chunk_transcript = _transcribe_single(client, tmp.name, language)
                if chunk_transcript:
                    full_transcript.append(chunk_transcript)
                os.unlink(tmp.name)
        return " ".join(full_transcript)
    except Exception as e:
        print(f"Chunked transcription error: {e}")
        return None
