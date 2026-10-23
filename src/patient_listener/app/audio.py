"""Streaming-audio boundary for the GPU deployment path.

The browser sends 16 kHz mono PCM frames as WebSocket binary messages. This module converts
model-specific ASR output into small, transport-neutral events and sends final text to the
existing session controller. It never stores audio or transcripts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable, Optional, Protocol

from ..config import Settings

__all__ = ["AsrEvent", "AudioPipeline", "audio_available", "build_pipeline"]

_MAX_PCM_FRAME_BYTES = 32_768
_MAX_TRANSCRIPT_CHARS = 500


@dataclass(frozen=True)
class AsrEvent:
    """One normalized result from streaming ASR; text is transient session data."""

    kind: str  # speech | partial | final | silence
    text: str = ""
    level_db: float | None = None  # internal only; never serialized to the browser
    voiced_samples: int = 0


class _StreamingAsr(Protocol):
    async def feed(
        self, frame: bytes, *, phrase_boosts: tuple[str, ...], boost_alpha: float
    ) -> Iterable[AsrEvent]: ...


class _TtsLike(Protocol):
    async def speak(self, text: str, voice: str) -> Iterable[bytes]: ...


def audio_available(settings: Settings) -> bool:
    """True only when the optional NeMo runtime is present and models are configured."""
    try:
        import nemo_toolkit  # type: ignore  # noqa: F401
    except Exception:
        return False
    return bool(settings.asr_model and settings.tts_model)


class AudioPipeline:
    """Bridge PCM frames into the authenticated application's session callbacks."""

    def __init__(
        self,
        asr: _StreamingAsr,
        tts: _TtsLike,
        *,
        on_speech: Callable[[], Awaitable[None]],
        on_partial: Callable[[str], Awaitable[None]],
        on_final: Callable[[str], Awaitable[None]],
        on_silence: Callable[[], Awaitable[None]],
        send_audio: Callable[[bytes], Awaitable[None]],
        phrase_boosts: Iterable[str] = (),
        boost_alpha: float = 2.0,
        voice: str = "Aria",
    ) -> None:
        self.asr = asr
        self.tts = tts
        self.on_speech = on_speech
        self.on_partial = on_partial
        self.on_final = on_final
        self.on_silence = on_silence
        self.send_audio = send_audio
        self.phrase_boosts = tuple(text for text in phrase_boosts if text.strip())
        self.boost_alpha = boost_alpha
        self.voice = voice

    async def on_frame(self, frame: bytes) -> None:
        """Process one bounded PCM frame and dispatch only normalized ASR events."""
        if not frame:
            return
        if len(frame) > _MAX_PCM_FRAME_BYTES:
            raise ValueError("audio frame exceeds the 32 KiB limit")
        events = await self.asr.feed(
            frame, phrase_boosts=self.phrase_boosts, boost_alpha=self.boost_alpha
        )
        for event in events:
            if event.kind == "speech":
                await self.on_speech()
            elif event.kind == "silence":
                await self.on_silence()
            elif event.kind in {"partial", "final"}:
                text = event.text.strip()
                if not text:
                    continue
                if len(text) > _MAX_TRANSCRIPT_CHARS:
                    raise ValueError("ASR transcript exceeds the 500 character limit")
                if event.kind == "partial":
                    await self.on_partial(text)
                else:
                    await self.on_final(text)
            else:
                raise ValueError(f"unknown ASR event: {event.kind}")

    async def say(self, text: str) -> None:
        """Render a listener line on the deploy box; the browser remains half-duplex."""
        async for chunk in await self.tts.speak(text, self.voice):
            await self.send_audio(chunk)


def build_pipeline(settings: Settings, **hooks) -> Optional[AudioPipeline]:  # noqa: ANN003
    """Construct production adapters on the GPU deploy box, or return ``None`` locally."""
    if not audio_available(settings):
        return None
    # The next deployment-specific subtask supplies NeMoStreamingAsr and MagpieTts here.
    # Keeping imports lazy protects the local backend demo from heavyweight voice dependencies.
    raise NotImplementedError("construct NeMo/Magpie adapters for the GPU deployment")
