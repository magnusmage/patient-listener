"""Audio-boundary tests: no GPU, model weights, audio storage, or network required."""

from __future__ import annotations

import unittest

from patient_listener.app.audio import AsrEvent, AudioPipeline


class FakeAsr:
    def __init__(self, events):
        self.events = events
        self.calls = []

    async def feed(self, frame, *, phrase_boosts, boost_alpha):
        self.calls.append((frame, phrase_boosts, boost_alpha))
        return self.events


class FakeTts:
    async def speak(self, text, voice):
        async def chunks():
            yield f"{voice}:{text}".encode()
        return chunks()


class AudioPipelineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.calls = []

        async def record(kind, text=None):
            self.calls.append((kind, text))

        self.record = record

    def pipeline(self, events):
        asr = FakeAsr(events)
        pipeline = AudioPipeline(
            asr, FakeTts(),
            on_speech=lambda: self.record("speech"),
            on_partial=lambda text: self.record("partial", text),
            on_final=lambda text: self.record("final", text),
            on_silence=lambda: self.record("silence"),
            send_audio=lambda chunk: self.record("audio", chunk),
            phrase_boosts=("Biscuit", "Can you open the window?"),
            boost_alpha=2.5,
        )
        return pipeline, asr

    async def test_forwards_events_and_patient_phrase_boosts(self):
        pipeline, asr = self.pipeline([
            AsrEvent("speech"), AsrEvent("partial", "bis"),
            AsrEvent("final", "Biscuit"), AsrEvent("silence"),
        ])
        await pipeline.on_frame(b"pcm")
        self.assertEqual(
            self.calls,
            [("speech", None), ("partial", "bis"), ("final", "Biscuit"), ("silence", None)],
        )
        self.assertEqual(asr.calls, [(b"pcm", ("Biscuit", "Can you open the window?"), 2.5)])

    async def test_rejects_oversized_audio_without_calling_asr(self):
        pipeline, asr = self.pipeline([])
        with self.assertRaisesRegex(ValueError, "32 KiB"):
            await pipeline.on_frame(b"x" * 32_769)
        self.assertEqual(asr.calls, [])

    async def test_rejects_unknown_asr_events(self):
        pipeline, _ = self.pipeline([AsrEvent("unexpected")])
        with self.assertRaisesRegex(ValueError, "unknown ASR event"):
            await pipeline.on_frame(b"pcm")

    async def test_streams_tts_chunks_without_storing_text(self):
        pipeline, _ = self.pipeline([])
        await pipeline.say("hello")
        self.assertEqual(self.calls, [("audio", b"Aria:hello")])


if __name__ == "__main__":
    unittest.main()
