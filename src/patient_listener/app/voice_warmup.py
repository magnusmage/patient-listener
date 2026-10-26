"""Synthetic startup-only inference; never opens a microphone or calls a text model."""
from __future__ import annotations


def warm_up(runtime, *, stream_factory=None):
    import numpy as np
    import torch
    if stream_factory is None:
        from .nemo_stream import NemoStream
        stream_factory = NemoStream
    clips = runtime.fixed_clips
    if not isinstance(clips, dict) or len(clips) < 10 or any(
        not isinstance(pcm, bytes) or not pcm or len(pcm) % 2 for pcm in clips.values()
    ):
        raise RuntimeError('Voice warm-up requires the complete PCM16 fixed audio bank')
    # Exercise VAD, streaming encoder/decoder and phrase-boosting Triton kernels.
    # No recognizer text is emitted, persisted or logged.
    with torch.inference_mode():
        stream = stream_factory(runtime, ('ready',), runtime.settings.boost_alpha)
        stream.feed(bytes(5120))  # 160ms, mono PCM16 at 16kHz
        stream.decode(np.zeros(32000, dtype=np.float32))
        if stream.buffer.step < 1:
            raise RuntimeError('Voice warm-up did not execute a streaming decoder step')
        stream.reset_stream()
        torch.cuda.synchronize()
    return True
