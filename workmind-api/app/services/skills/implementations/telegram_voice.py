"""Telegram voice message transcription skill."""
from __future__ import annotations
import logging
import os
import tempfile

logger = logging.getLogger(__name__)

# Whisper model size: tiny (fastest, ~40MB) or small (~240MB)
# Override with WORKMIND_WHISPER_MODEL env var
_WHISPER_MODEL = os.environ.get("WORKMIND_WHISPER_MODEL", "tiny")
_whisper_instance = None


def _get_whisper():
    """Lazy-load faster-whisper model (singleton)."""
    global _whisper_instance
    if _whisper_instance is None:
        try:
            from faster_whisper import WhisperModel
            _whisper_instance = WhisperModel(_WHISPER_MODEL, device="cpu", compute_type="int8")
            logger.info("faster-whisper loaded: model=%s", _WHISPER_MODEL)
        except Exception as exc:
            logger.error("faster-whisper load failed: %s", exc)
    return _whisper_instance


async def transcribe_voice(file_path: str, **kwargs) -> str:
    """
    Transcribe an audio file using faster-whisper (local, CPU, int8).
    Falls back to '[trascrizione non disponibile]' if model not loaded.
    """
    import asyncio
    model = _get_whisper()
    if model is None:
        return "[trascrizione non disponibile — whisper non disponibile]"

    def _run():
        segments, info = model.transcribe(file_path, language="it", beam_size=1)
        return " ".join(seg.text for seg in segments).strip(), info.language

    try:
        loop = asyncio.get_event_loop()
        text, detected_lang = await loop.run_in_executor(None, _run)
        logger.info("voice transcribed: lang=%s, len=%d", detected_lang, len(text))
        return text or "[silenzio o audio non chiaro]"
    except Exception as exc:
        logger.warning("transcription failed: %s", exc)
        return "[trascrizione non disponibile]"


async def download_telegram_file(file_id: str, bot_token: str) -> str | None:
    """Download a Telegram file to a temp path, return local path."""
    import httpx
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}")
        if r.status_code != 200:
            return None
        file_path = r.json()["result"]["file_path"]
        dl = await client.get(f"https://api.telegram.org/file/bot{bot_token}/{file_path}")
        suffix = os.path.splitext(file_path)[1] or ".oga"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
            f.write(dl.content)
            return f.name


async def handle_voice_message(file_id: str, org_id: str, db, bot_token: str, ollama_url: str = "") -> str:
    """Full pipeline: download → transcribe → route through AI."""
    tmp = await download_telegram_file(file_id, bot_token)
    if not tmp:
        return "❌ Impossibile scaricare il messaggio vocale."
    try:
        transcript = await transcribe_voice(tmp)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass

    if not transcript or "non disponibile" in transcript:
        return "❌ Trascrizione non riuscita. Riprova o scrivi il messaggio."

    # Route transcription through standard AI pipeline
    from app.services.channel_router import handle_incoming_message
    reply = await handle_incoming_message(
        db=db,
        channel_type="telegram",
        external_id=f"voice_{org_id}",
        text=f"[Messaggio vocale]: {transcript}",
    )
    return f"🎤 _{transcript}_\n\n{reply}"


def make_telegram_voice_job(org_id: str, config: dict):
    async def _noop():
        pass
    return _noop
