"""Cache-aware NeMo ASR and Magpie inference for the single-session GPU development path.

Optional imports stay inside adapter construction. No raw audio/transcript is written to disk.
NeMo reference APIs: CacheAwareStreamingAudioBuffer and conformer_stream_step.
"""
from __future__ import annotations
import copy

from .audio import AsrEvent


class NemoStream:
    def __init__(self, runtime, phrases, alpha):
        import torch
        import numpy as np
        from omegaconf import OmegaConf
        from nemo.collections.asr.parts.utils.streaming_utils import CacheAwareStreamingAudioBuffer
        self.torch, self.np = torch, np
        self.model = runtime.asr
        self.vad = copy.deepcopy(runtime.vad)
        self.vad.reset_states()
        self.Buffer = CacheAwareStreamingAudioBuffer
        cfg = OmegaConf.create(OmegaConf.to_container(self.model.cfg.decoding, resolve=True))
        OmegaConf.set_struct(cfg, False)
        cfg.strategy = 'greedy_batch'
        cfg.greedy.use_cuda_graph_decoder = False
        cfg.greedy.boosting_tree = {'key_phrases_list': list(phrases)}
        cfg.greedy.boosting_tree_alpha = alpha if phrases else 0.0
        self.model.change_decoding_strategy(cfg)
        self.pending = bytearray()
        self.speaking = False
        self.quiet_samples = 0
        self.segment_samples = 0
        self.reset_decoder()

    def reset_stream(self):
        """Discard recognition and VAD history at playback/listening boundaries."""
        self.pending.clear()
        self.vad.reset_states()
        self.speaking = False
        self.quiet_samples = 0
        self.reset_decoder()

    def reset_decoder(self):
        self.buffer = self.Buffer(self.model, online_normalization=True)
        self.cache = self.model.encoder.get_initial_cache_state(batch_size=1)
        self.previous = None
        self.predictions = None
        self.text = ''
        self.segment_samples = 0

    def decode(self, samples):
        self.buffer.append_audio(samples, stream_id=-1 if self.buffer.buffer is None else 0)
        cfg = self.model.encoder.streaming_cfg
        while self.buffer.buffer is not None:
            size = cfg.chunk_size
            size = size[0 if self.buffer.buffer_idx == 0 else 1] if isinstance(size, (list, tuple)) else size
            # OmegaConf ListConfig also supports indexing but is not a Python list.
            if not isinstance(size, (int, float)):
                size = size[0 if self.buffer.buffer_idx == 0 else 1]
            if self.buffer.buffer.size(-1) - self.buffer.buffer_idx < int(size):
                break
            chunk, lengths = next(iter(self.buffer))
            drop = 0 if self.buffer.step == 1 else cfg.drop_extra_pre_encoded
            result = self.model.conformer_stream_step(
                processed_signal=chunk, processed_signal_length=lengths,
                cache_last_channel=self.cache[0], cache_last_time=self.cache[1],
                cache_last_channel_len=self.cache[2], previous_hypotheses=self.previous,
                previous_pred_out=self.predictions, keep_all_outputs=False,
                drop_extra_pre_encoded=drop, return_transcription=True,
            )
            self.predictions, texts, c0, c1, c2, self.previous = result
            self.cache = (c0, c1, c2)
            self.text = getattr(texts[0], 'text', texts[0]) if texts else self.text
        return self.text

    def feed(self, frame):
        if len(frame) % 2:
            raise ValueError('Expected PCM16 audio')
        self.pending.extend(frame)
        events = []
        with self.torch.inference_mode():
            while len(self.pending) >= 5120:  # 160 ms at 16 kHz / PCM16
                block = bytes(self.pending[:5120]); del self.pending[:5120]
                samples = self.np.frombuffer(block, dtype='<i2').astype('float32') / 32768.0
                probabilities = [float(self.vad(self.torch.from_numpy(samples[i:i+512].copy()), 16000))
                                 for i in range(0, 2560, 512)]
                voiced = max(probabilities) >= .5
                if voiced:
                    self.quiet_samples = 0
                    events.append(AsrEvent('speech'))
                    self.speaking = True
                else:
                    self.quiet_samples += 2560
                if self.speaking:
                    self.segment_samples += 2560
                    if self.segment_samples > 16000 * 60:
                        raise ValueError('Continuous utterance exceeds development buffer limit')
                    old = self.text
                    text = self.decode(samples)
                    if text and text != old:
                        events.append(AsrEvent('partial', text))
                    if not voiced and self.quiet_samples >= 10240:  # close ASR segment, not controller turn
                        if self.text.strip():
                            events.append(AsrEvent('final', self.text.strip()))
                        self.speaking = False
                        self.reset_decoder()
                        events.append(AsrEvent('silence'))
                elif self.quiet_samples == 2560:
                    events.append(AsrEvent('silence'))
        return events


def synthesize(runtime, text):
    import torch
    with torch.inference_mode():
        audio, lengths = runtime.tts.do_tts(
            text, language='en', apply_TN=False, speaker_index=0,
        )
        data = audio[0, :int(lengths[0])].detach().float().cpu().numpy()
    return (data.clip(-1, 1) * 32767).astype('<i2').tobytes()
