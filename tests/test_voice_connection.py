"""Voice protocol and cancellation tests; no GPU or live model requests."""
import asyncio
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from patient_listener.app.audio import AsrEvent
from patient_listener.voice.processing import hint_profile
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


    async def test_closing_replaces_queued_audio_and_waits_for_new_playback(self):
        c, events = self.connection()
        c.session.set_audio_busy = lambda busy: None
        with patch('patient_listener.app.nemo_stream.NemoStream', Decoder), patch(
            'patient_listener.app.nemo_stream.synthesize', return_value=b'\0\0') as synth:
            await c.start()
            try:
                await c.send({'type':'reply','text':'Old first. Old queued.'})
                await events.get(); await events.get(); await events.get()
                self.assertTrue(c.busy)
                await c.send({'type':'reply','text':'Well done today.','replace_audio':True})
                self.assertEqual((await events.get())['type'], 'audioCancel')
                self.assertEqual((await events.get())['text'], 'Well done today.')
                start = await events.get()
                self.assertEqual(start['type'], 'audioStart')
                await events.get()  # audioEnd
                c.acknowledge(start['id'])
                self.assertEqual((await asyncio.wait_for(events.get(),1))['type'], 'audioIdle')
                texts = [call.args[1] for call in synth.call_args_list]
                self.assertEqual(texts, ['Old first.', 'Well done today.'])
            finally: await c.close()


    async def test_cached_hint_playback_does_not_synthesize_and_waits_for_ack(self):
        c, events = self.connection()
        c.runtime.settings.tts_model = 'model'
        c.runtime.settings.tts_voice = 'voice'
        c.session.person_id = 'person'
        from unittest.mock import Mock
        c.session.store = SimpleNamespace(hint_audio=Mock(return_value=b'\1\0'))
        with patch('patient_listener.app.nemo_stream.NemoStream', Decoder), patch(
            'patient_listener.app.nemo_stream.synthesize') as synth:
            await c.start()
            try:
                await c.send({'type':'hint','word_id':'word','level':1,'text':'A family pet.'})
                self.assertEqual((await events.get())['type'],'hint')
                start = await asyncio.wait_for(events.get(),1)
                self.assertEqual(start['type'],'audioStart')
                self.assertEqual((await events.get())['type'],'audioEnd')
                c.socket.send_bytes.assert_awaited_once_with(b'\1\0')
                synth.assert_not_called()
                self.assertTrue(c.busy)
                c.acknowledge(start['id'])
                self.assertEqual((await asyncio.wait_for(events.get(),1))['type'],'audioIdle')
                c.session.store.hint_audio.assert_called_once_with(
                    'person','word',1,'A family pet.','model','voice',
                    profile=hint_profile(c.runtime.settings))
            finally: await c.close()


    async def test_measured_level_is_internal_and_follows_final_safety_processing(self):
        c, _ = self.connection()
        calls = []
        async def final(text):calls.append(('text',text))
        async def measured(level,count):calls.append(('level',level,count))
        c.session.on_audio_final.side_effect=final
        c.session.on_audio_level=measured
        class MeasuredDecoder(Decoder):
            def feed(self,frame):return [AsrEvent('final','Good morning.',-23,2560)]
        with patch('patient_listener.app.nemo_stream.NemoStream',MeasuredDecoder):
            await c.start()
            try:
                await c.frame(b'\0\0')
                for _ in range(100):
                    if len(calls)==2:break
                    await asyncio.sleep(.01)
                self.assertEqual(calls,[('text','Good morning.'),('level',-23,2560)])
                c._set_playback(True)
                await c.frame(b'\0\0')
                await asyncio.sleep(.05)
                self.assertEqual(len(calls),2)
            finally:await c.close()

    async def test_changed_capture_discards_inflight_levels(self):
        c, _ = self.connection()
        c.session.on_audio_level=AsyncMock()
        entered, release = threading.Event(), threading.Event()
        class SlowMeasuredDecoder(Decoder):
            def feed(self,frame):
                entered.set();release.wait(2)
                return [AsrEvent('final','Old microphone',-23,2560)]
        with patch('patient_listener.app.nemo_stream.NemoStream',SlowMeasuredDecoder):
            await c.start()
            try:
                await c.frame(b'\0\0')
                for _ in range(100):
                    if entered.is_set():break
                    await asyncio.sleep(.01)
                self.assertTrue(entered.is_set())
                c.invalidate_input();release.set()
                await asyncio.sleep(.05)
                c.session.on_audio_level.assert_not_awaited()
                c.session.on_audio_final.assert_not_awaited()
            finally:release.set();await c.close()


    async def test_fixed_backchannel_uses_cached_pcm_not_live_magpie(self):
        c,events=self.connection()
        c.runtime.fixed_clips={'mm':b'\1\0'}
        with patch('patient_listener.app.nemo_stream.NemoStream',Decoder), patch(
                'patient_listener.app.nemo_stream.synthesize') as synth:
            await c.start()
            try:
                await c.send({'type':'backchannel','key':'mm','caption':'mm'})
                await events.get()
                start=await asyncio.wait_for(events.get(),1)
                await events.get()
                c.socket.send_bytes.assert_awaited_once_with(b'\1\0')
                synth.assert_not_called()
                c.acknowledge(start['id'])
            finally:await c.close()

    async def test_missing_hint_stays_text_only_without_live_synthesis(self):
        c,events=self.connection()
        c.runtime.settings.tts_model='m';c.runtime.settings.tts_voice='v'
        c.session.person_id='p'
        from unittest.mock import Mock
        c.session.store=SimpleNamespace(hint_audio=Mock(return_value=None))
        with patch('patient_listener.app.nemo_stream.synthesize') as synth:
            await c.send({'type':'hint','text':'A family pet.','word_id':'w','level':1})
            self.assertEqual((await events.get())['type'],'hint')
            self.assertEqual((await events.get())['type'],'voiceNotice')
            self.assertTrue(c.output.empty())
            synth.assert_not_called()
        await c.close()


    async def test_rest_and_resume_invalidate_old_decoder_results(self):
        c,events=self.connection()
        c.input.put_nowait((b'xx',c.input_epoch))
        await c.send({'type':'state','state':'resting','replace_audio':True})
        rest_epoch=c.input_epoch
        self.assertGreater(rest_epoch,0)
        self.assertTrue(c.input.empty())
        c.input.put_nowait((b'xx',rest_epoch))
        await c.send({'type':'prompt','text':'','profile':'saving_energy'})
        self.assertGreater(c.input_epoch,rest_epoch)
        self.assertTrue(c.input.empty())
        self.assertFalse(c._rest_input)
        await c.close()
