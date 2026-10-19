"""Audio transport scaffold (the GPU / deploy box path).

The patient app's ``LiveDriver`` streams 16 kHz mono PCM frames over the same WebSocket. On the
deploy box those frames are transcribed by a NeMo streaming ASR adapter and the controller's
spoken lines are rendered by a Magpie TTS adapter - both behind the existing ``Asr`` / ``Tts``
ports (``ports.py``), so the core never changes.

This module is **import-guarded and inert offline**: with no ``voice`` extra, no GPU and no
model weights, :func:`build_pipeline` returns ``None`` and the server simply ignores binary
frames (the text/logic transport drives everything in the sandbox). The structure below is the
real wiring the deploy box fills in; it is intentionally not exercised by the offline tests.

Wiring (deploy box):

    asr = NeMoStreamingAsr(settings)                 # implements ports.Asr
    tts = MagpieTts(settings)                         # implements ports.Tts
    pipeline = AudioPipeline(asr, tts, on_words=..., on_silence=...)
    # feed inbound binary frames:        await pipeline.on_frame(frame)
    # turn a Speak/Play action into audio: async for chunk in pipeline.say(text): ws.send(chunk)

The ``on_words`` / ``on_silence`` callbacks feed the orchestrator exactly the ``("heard", ...)``
and ``("silence", ...)`` events the text transport already produces, so both transports converge
on one :class:`~patient_listener.app.session.AppSession`.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Optional, Protocol

from ..config import Settings

__all__ = ["AudioPipeline", "build_pipeline", "audio_available"]


class _AsrLike(Protocol):
    async def stream(self, frames): ...  # noqa: ANN001 - see ports.Asr


class _TtsLike(Protocol):
    async def speak(self, text: str, voice: str): ...


def audio_available(settings: Settings) -> bool:
    """True only when the real ASR/TTS adapters can be constructed (``voice`` extra + weights)."""
    try:
        import nemo_toolkit  # type: ignore  # noqa: F401
    except Exception:
        return False
    return bool(settings.asr_model and settings.tts_model)


class AudioPipeline:
    """Bridges binary PCM frames to the orchestrator and renders spoken lines to audio.

    Constructed only on the deploy box. ``on_words``/``on_silence`` are the orchestrator hooks;
    ``send_audio`` streams TTS chunks back to the browser.
    """

    def __init__(
        self,
        asr: _AsrLike,
        tts: _TtsLike,
        on_words: Callable[[str], Awaitable[None]],
        on_silence: Callable[[], Awaitable[None]],
        send_audio: Callable[[bytes], Awaitable[None]],
        voice: str = "Aria",
    ) -> None:
        self.asr = asr
        self.tts = tts
        self.on_words = on_words
        self.on_silence = on_silence
        self.send_audio = send_audio
        self.voice = voice

    async def on_frame(self, frame: bytes) -> None:  # pragma: no cover - deploy box only
        """Push one inbound PCM frame through streaming ASR; emit words/silence to the session."""
        raise NotImplementedError("wire NeMo streaming ASR on the deploy box")

    async def say(self, text: str) -> None:  # pragma: no cover - deploy box only
        """Render ``text`` with Magpie TTS and stream the chunks to the browser (half-duplex)."""
        async for chunk in await self.tts.speak(text, self.voice):
            await self.send_audio(chunk)


def build_pipeline(settings: Settings, **hooks) -> Optional[AudioPipeline]:  # noqa: ANN003
    """Construct the pipeline on the deploy box, or ``None`` offline (the usual sandbox case)."""
    if not audio_available(settings):
        return None
    # Deploy box: import and construct the real adapters here, then return AudioPipeline(...).
    # Kept lazy so importing this module never requires the voice extra.
    raise NotImplementedError(  # pragma: no cover - deploy box only
        "construct NeMo/Magpie adapters and return AudioPipeline(asr, tts, **hooks)"
    )
