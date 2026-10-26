"""GPU model lifetime. Imported safely on machines without PyTorch or NeMo."""
from __future__ import annotations

from dataclasses import dataclass, field
import threading
import gc
import time
import logging
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
    fixed_clips: dict[str,bytes] = field(default_factory=dict)
    pipecat_version: str | None = None
    warmup_passed: bool = False

    @classmethod
    def load(cls, settings: Settings) -> "VoiceRuntime":
        from .pipecat_pipeline import require_pipecat
        pipeline_version = require_pipecat()
        import torch
        from nemo.collections.asr.models import ASRModel
        from nemo.collections.tts.models import MagpieTTSModel
        from silero_vad import load_silero_vad

        if not torch.cuda.is_available():
            raise RuntimeError('VOICE_ENABLED requires a CUDA-capable PyTorch environment')
        started = time.perf_counter()
        asr = tts = runtime = None
        try:
            asr = ASRModel.from_pretrained(model_name=settings.asr_model).to('cuda').eval()
            tts = MagpieTTSModel.from_pretrained(settings.tts_model).to('cuda').eval()
            asr.encoder.set_default_att_context_size([70, 1])
            vad = load_silero_vad()
            torch.cuda.synchronize()
            runtime = cls(asr, tts, torch.cuda.get_device_name(0),
                       round(time.perf_counter() - started, 3),
                       round(torch.cuda.memory_allocated() / 1024**3, 3), vad, settings)
            runtime.pipecat_version = pipeline_version
            from ..voice.fixed_audio import prepare_fixed
            count = prepare_fixed(runtime)
            logging.getLogger("uvicorn.error.patient_listener.voice").info(
                "Prepared fixed audio clips count=%d", count)
            from .voice_warmup import warm_up
            runtime.warmup_passed = warm_up(runtime)
            logging.getLogger("uvicorn.error.patient_listener.voice").info(
                "Voice inference warm-up passed input_hz=16000 output_hz=22050")
            runtime.load_seconds = round(time.perf_counter() - started, 3)
            return runtime
        except BaseException:
            # Release partially loaded model references when the second model cannot load.
            if runtime is not None:
                runtime.asr = runtime.tts = runtime.vad = None
                runtime.fixed_clips.clear()
            asr = tts = None
            gc.collect()
            torch.cuda.empty_cache()
            raise

    def close(self) -> None:
        import torch
        self.warmup_passed = False
        self.asr = None
        self.tts = None
        self.vad = None
        self.fixed_clips.clear()
        gc.collect()
        torch.cuda.empty_cache()
