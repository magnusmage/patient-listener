"""GPU model lifetime. Imported safely on machines without PyTorch or NeMo."""
from __future__ import annotations

from dataclasses import dataclass, field
import threading
import gc
import time
from typing import Any

from ..config import Settings


@dataclass
class VoiceRuntime:
    asr: Any
    tts: Any
    device: str
    load_seconds: float
    allocated_gib: float
    vad: Any = None
    settings: Any = None
    gpu_lock: Any = field(default_factory=threading.Lock)

    @classmethod
    def load(cls, settings: Settings) -> "VoiceRuntime":
        import torch
        from nemo.collections.asr.models import ASRModel
        from nemo.collections.tts.models import MagpieTTSModel
        from silero_vad import load_silero_vad

        if not torch.cuda.is_available():
            raise RuntimeError('VOICE_ENABLED requires a CUDA-capable PyTorch environment')
        started = time.perf_counter()
        asr = tts = None
        try:
            asr = ASRModel.from_pretrained(model_name=settings.asr_model).to('cuda').eval()
            tts = MagpieTTSModel.from_pretrained(settings.tts_model).to('cuda').eval()
            asr.encoder.set_default_att_context_size([70, 1])
            vad = load_silero_vad()
            torch.cuda.synchronize()
            return cls(asr, tts, torch.cuda.get_device_name(0),
                       round(time.perf_counter() - started, 3),
                       round(torch.cuda.memory_allocated() / 1024**3, 3), vad, settings)
        except BaseException:
            # Release partially loaded model references when the second model cannot load.
            asr = tts = None
            gc.collect()
            torch.cuda.empty_cache()
            raise

    def close(self) -> None:
        import torch
        self.asr = None
        self.tts = None
        self.vad = None
        gc.collect()
        torch.cuda.empty_cache()
