"""Voice protocol and cancellation tests; no GPU or live model requests."""
import asyncio
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from patient_listener.app.audio import AsrEvent
from patient_listener.app.voice_connection import VoiceConnection


class Decoder:
    def __init__(self, *args): pass
    def reset_stream(self): pass
    def feed(self, frame): return [AsrEvent('speech'), AsrEvent('partial','bis'), AsrEvent('final','Biscuit')]


class ConnectionTests(unittest.IsolatedAsyncioTestCase):
    def connection(self):
        runtime = SimpleNamespace(gpu_lock=threading.Lock(), settings=SimpleNamespace(boost_alpha=2.0))
        session = SimpleNamespace(words=[], _cancel_ticker=lambda: None, close=lambda: None,
            on_audio_speech=AsyncMock(), on_audio_partial=AsyncMock(),
            on_audio_final=AsyncMock(), on_audio_silence=AsyncMock(), handle=AsyncMock())
        socket = SimpleNamespace(send_bytes=AsyncMock(), close=AsyncMock())
        events = asyncio.Queue()
        async def send(event): await events.put(event)
        return VoiceConnection(runtime,session,socket,send), events

    async def test_audio_waits_for_correct_playback_ack(self):
        c, events = self.connection()
        with patch('patient_listener.app.nemo_stream.NemoStream', Decoder), patch(
            'patient_listener.app.nemo_stream.synthesize', return_value=b'\0\0'):
            await c.start()
            try:
                await c.send({'type':'reply','text':'Hello.'})
                self.assertEqual((await events.get())['type'],'reply')
                start = await asyncio.wait_for(events.get(),1)
                self.assertEqual(start['type'],'audioStart')
                self.assertEqual((await events.get())['type'],'audioEnd')
                self.assertTrue(c.busy)
                await c.frame(b'\0\0')
                self.assertEqual(c.input.qsize(), 1)  # still captured for spoken Stop
                c.acknowledge(-1)
                self.assertFalse(c.played.is_set())
                c.acknowledge(start['id'])
                self.assertEqual((await asyncio.wait_for(events.get(),1))['type'],'audioIdle')
                c.socket.send_bytes.assert_awaited_once_with(b'\0\0')
            finally: await c.close()

    async def test_asr_events_reach_session(self):
        c, events = self.connection()
        with patch('patient_listener.app.nemo_stream.NemoStream', Decoder):
            await c.start()
            try:
                await c.frame(b'\0\0')
                for _ in range(100):
                    if c.session.on_audio_final.await_count: break
                    await asyncio.sleep(.01)
                c.session.on_audio_speech.assert_awaited_once()
                c.session.on_audio_partial.assert_awaited_once_with('bis')
                c.session.on_audio_final.assert_awaited_once_with('Biscuit')
            finally: await c.close()

    async def test_safety_discards_pending_gpu_audio(self):
        c, events = self.connection()
        entered, release = threading.Event(), threading.Event()
        def synth(*args):
            entered.set(); release.wait(3); return b'late audio'
        with patch('patient_listener.app.nemo_stream.NemoStream', Decoder), patch(
            'patient_listener.app.nemo_stream.synthesize', side_effect=synth):
            await c.start()
            try:
                await c.send({'type':'reply','text':'Hello.'})
                await events.get(); await events.get()
                for _ in range(100):
                    if entered.is_set(): break
                    await asyncio.sleep(.01)
                self.assertTrue(entered.is_set())
                await c.send({'type':'safety','card':'stroke_signs'})
                self.assertEqual((await events.get())['type'],'safety')
                c.socket.close.assert_awaited_once_with(code=1000)
                release.set()
            finally:
                release.set(); await c.close()
            c.socket.send_bytes.assert_not_awaited()

    async def test_audio_queue_is_bounded_and_rejects_bad_pcm(self):
        c, _ = self.connection()
        with self.assertRaises(ValueError): await c.frame(b'x')
        for _ in range(64): await c.frame(b'\0\0')
        with self.assertRaises(asyncio.QueueFull): await c.frame(b'\0\0')
        await c.close()

    async def test_playback_speech_is_ignored_but_partial_exact_stop_ends_session(self):
        c, events = self.connection()
        class PlaybackDecoder(Decoder):
            def feed(self, frame):
                if frame == b'\x01\x00':
                    return [AsrEvent('partial', 'Stop!')]
                return [AsrEvent('speech'), AsrEvent('partial', 'stop now'),
                        AsrEvent('final', 'Biscuit'), AsrEvent('silence')]
        async def handle(message):
            if message['type'] == 'stop':
                await c.send({'type': 'ended', 'reason': 'stop'})
        c.session.handle.side_effect = handle
        with patch('patient_listener.app.nemo_stream.NemoStream', PlaybackDecoder), patch(
            'patient_listener.app.nemo_stream.synthesize', return_value=b'\0\0'):
            await c.start()
            try:
                await c.send({'type':'reply','text':'Hello.'})
                await events.get(); await events.get(); await events.get()
                await c.frame(b'\0\0')
                await asyncio.sleep(.05)
                c.session.handle.assert_not_awaited()
                c.session.on_audio_speech.assert_not_awaited()
                c.session.on_audio_partial.assert_not_awaited()
                c.session.on_audio_final.assert_not_awaited()
                c.session.on_audio_silence.assert_not_awaited()
                await c.frame(b'\x01\x00')
                ended = await asyncio.wait_for(events.get(), 1)
                self.assertEqual(ended['type'], 'ended')
                c.session.handle.assert_awaited_once_with({'type':'stop'})
                c.socket.close.assert_awaited_once_with(code=1000)
                self.assertTrue(c.closed)
            finally: await c.close()

    async def test_playback_boundary_discards_inflight_transcript(self):
        c, _ = self.connection()
        entered, release = threading.Event(), threading.Event()
        class SlowDecoder(Decoder):
            def feed(self, frame):
                entered.set(); release.wait(2)
                return [AsrEvent('final', 'Biscuit')]
        with patch('patient_listener.app.nemo_stream.NemoStream', SlowDecoder):
            await c.start()
            try:
                await c.frame(b'\0\0')
                for _ in range(100):
                    if entered.is_set(): break
                    await asyncio.sleep(.01)
                self.assertTrue(entered.is_set())
                c._set_playback(True)
                release.set()
                await asyncio.sleep(.05)
                c.session.on_audio_final.assert_not_awaited()
                c._set_playback(False)
                await c.frame(b'\0\0')
                for _ in range(100):
                    if c.session.on_audio_final.await_count: break
                    await asyncio.sleep(.01)
                c.session.on_audio_final.assert_awaited_once_with('Biscuit')
            finally:
                release.set(); await c.close()
