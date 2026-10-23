"""Real Pipecat 1.12 lifecycle/frames with synthetic models, no GPU or model calls."""
import asyncio
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from patient_listener.app.audio import AsrEvent
from patient_listener.app.voice_connection import VoiceConnection
from patient_listener.app.pipecat_pipeline import (
    MicrophoneFrame, SpeechFrame, FinalFrame, PartialFrame, PlaybackFrame, require_pipecat,
)


class Decoder:
    def __init__(self, *args): pass
    def reset_stream(self): pass
    def feed(self, frame): return [AsrEvent('speech'), AsrEvent('final','Biscuit'), AsrEvent('silence')]


class PipecatTests(unittest.IsolatedAsyncioTestCase):
    def connection(self):
        runtime=SimpleNamespace(gpu_lock=threading.Lock(), settings=SimpleNamespace(boost_alpha=2))
        session=SimpleNamespace(words=[], _cancel_ticker=lambda:None, close=lambda:None,
            on_audio_speech=AsyncMock(),on_audio_partial=AsyncMock(),on_audio_final=AsyncMock(),
            on_audio_silence=AsyncMock(),handle=AsyncMock())
        socket=SimpleNamespace(send_bytes=AsyncMock(),close=AsyncMock())
        events=asyncio.Queue()
        return VoiceConnection(runtime,session,socket,events.put),events

    async def test_real_pipeline_rates_no_automatic_turn_owner_and_cleanup(self):
        connection,_=self.connection()
        with patch('patient_listener.app.nemo_stream.NemoStream',Decoder):
            await connection.start()
            pipeline=connection.pipeline
            task=pipeline.task
            try:
                self.assertEqual(pipeline.version,'1.12.0')
                self.assertEqual(pipeline.worker.params.audio_in_sample_rate,16000)
                self.assertEqual(pipeline.worker.params.audio_out_sample_rate,22050)
                self.assertIsNone(pipeline.worker._idle_timeout_secs)
                self.assertEqual([type(p).__name__ for p in pipeline.processors],
                                 ['NeMoInput','Patience','MagpieOutput','BrowserOutput'])
                await pipeline.receive(b'\0\0',connection.input_epoch)
                connection.session.on_audio_final.assert_awaited_once_with('Biscuit')
            finally:
                await connection.close()
            self.assertTrue(task.done())
            self.assertIsNone(connection.pipeline)

    async def test_vad_start_is_an_edge_and_continuing_speech_keeps_its_own_frame(self):
        connection,_=self.connection()
        class Speaking(Decoder):
            def feed(self,frame):return [AsrEvent('speech'),AsrEvent('speech'),AsrEvent('silence')]
        with patch('patient_listener.app.nemo_stream.NemoStream',Speaking):
            await connection.start()
            try:
                kinds=[]
                @connection.pipeline.processors[1].event_handler('on_before_process_frame')
                async def observe(processor,frame):
                    if 'event' in frame.metadata:
                        kinds.append(type(frame).__name__)
                await connection.pipeline.receive(b'\0\0',connection.input_epoch)
                self.assertEqual(kinds,['VADUserStartedSpeakingFrame','UserSpeakingFrame',
                                        'VADUserStoppedSpeakingFrame'])
                self.assertEqual(connection.session.on_audio_speech.await_count,2)
            finally:
                await connection.close()

    async def test_framework_frames_have_redacted_string_and_repr(self):
        frames=[SpeechFrame(text='private wording'),
                FinalFrame(text='private wording',user_id='',timestamp=''),
                PartialFrame(text='private wording',user_id='',timestamp=''),
                MicrophoneFrame(audio=b'private audio',sample_rate=16000,num_channels=1),
                PlaybackFrame(audio=b'private audio',sample_rate=22050,num_channels=1)]
        for frame in frames:
            for rendered in (str(frame),repr(frame)):
                self.assertNotIn('private wording',rendered)
                self.assertNotIn('private audio',rendered)

    async def test_cached_output_is_byte_identical_and_bypasses_synthesis(self):
        connection,_=self.connection()
        with patch('patient_listener.app.nemo_stream.NemoStream',Decoder), \
             patch('patient_listener.app.nemo_stream.synthesize') as synth:
            await connection.start()
            try:
                await connection.pipeline.speak('A saved hint.',b'\1\0'*100)
                connection.socket.send_bytes.assert_awaited_once_with(b'\1\0'*100)
                synth.assert_not_called()
            finally:
                await connection.close()

    async def test_input_processor_error_closes_voice_without_private_error(self):
        connection,events=self.connection()
        class Broken(Decoder):
            def feed(self,frame):raise RuntimeError('private transcript must not escape')
        with patch('patient_listener.app.nemo_stream.NemoStream',Broken):
            await connection.start()
            try:
                await connection.frame(b'\0\0')
                event=await asyncio.wait_for(events.get(),1)
                self.assertEqual(event,{'type':'voiceError','code':'speech_input_failed'})
                connection.socket.close.assert_awaited_once_with(code=1011)
            finally:
                await connection.close()

    async def test_final_safety_prevents_level_feedback_and_later_events(self):
        connection,events=self.connection()
        connection.session.on_audio_level=AsyncMock()
        class Safety(Decoder):
            def feed(self,frame):return [AsrEvent('final','my arm is weak',-20,2560),
                                        AsrEvent('final','Biscuit')]
        async def final(text):await connection.send({'type':'safety','card':'stroke_signs'})
        connection.session.on_audio_final.side_effect=final
        with patch('patient_listener.app.nemo_stream.NemoStream',Safety):
            await connection.start()
            try:
                await connection.frame(b'\0\0')
                self.assertEqual((await asyncio.wait_for(events.get(),1))['type'],'safety')
                connection.session.on_audio_final.assert_awaited_once_with('my arm is weak')
                connection.session.on_audio_level.assert_not_awaited()
            finally:
                await connection.close()

    async def test_synthesis_watchdog_fails_before_worker_finishes_and_discards_audio(self):
        connection,events=self.connection()
        entered,release=threading.Event(),threading.Event()
        def slow(*args):
            entered.set();release.wait(2);return b'\1\0'
        with patch('patient_listener.app.nemo_stream.NemoStream',Decoder), \
             patch('patient_listener.app.nemo_stream.synthesize',side_effect=slow), \
             patch('patient_listener.app.pipecat_pipeline.SYNTHESIS_STALL_S',.03):
            await connection.start()
            try:
                await connection.send({'type':'reply','text':'Hello.'})
                await events.get()
                await events.get()
                self.assertTrue(await asyncio.to_thread(entered.wait,1))
                error=await asyncio.wait_for(events.get(),1)
                self.assertEqual(error,{'type':'voiceError','code':'speech_output_stalled'})
                self.assertFalse(release.is_set())
                connection.socket.send_bytes.assert_not_awaited()
                closing=asyncio.create_task(connection.close())
                await asyncio.sleep(.02)
                self.assertFalse(closing.done())
                release.set()
                await closing
                connection.socket.send_bytes.assert_not_awaited()
            finally:
                release.set()
                await connection.close()

    async def test_unexpected_framework_shutdown_notifies_client(self):
        connection,events=self.connection()
        with patch('patient_listener.app.nemo_stream.NemoStream',Decoder):
            await connection.start()
            try:
                await connection.pipeline.worker.cancel()
                event=await asyncio.wait_for(events.get(),1)
                self.assertEqual(event,{'type':'voiceError','code':'voice_pipeline_failed'})
                self.assertTrue(connection.closed)
            finally:
                await connection.close()

    async def test_version_guard_rejects_unverified_framework(self):
        with patch('patient_listener.app.pipecat_pipeline.version',return_value='1.13.0'):
            with self.assertRaisesRegex(RuntimeError,'1.12.0'):
                require_pipecat()


class PipecatWebSocketTests(unittest.TestCase):
    def test_authenticated_mixed_control_and_pcm_reaches_actual_pipeline(self):
        import json
        from fastapi.testclient import TestClient
        from patient_listener.app.server import create_app
        from patient_listener.config import Settings
        from unittest.mock import Mock
        settings=Settings(voice_enabled=True,ai_enabled=False,nebius_api_key='')
        runtime=SimpleNamespace(gpu_lock=threading.Lock(),settings=settings,
                                pipecat_version='1.12.0',close=Mock())
        with patch('patient_listener.app.server.VoiceRuntime.load',return_value=runtime), \
             patch('patient_listener.app.nemo_stream.NemoStream',Decoder), \
             patch('patient_listener.app.nemo_stream.synthesize',return_value=b'\0\0'):
            with TestClient(create_app(settings)) as client:
                health=client.get('/healthz').json()
                self.assertEqual(health['pipeline_framework'],'pipecat')
                self.assertFalse(health['streaming_ready'])
                device='a'*48
                token=client.get('/api/session',params={'person':'margaret'},
                                 headers={'X-PL-Device':device}).json()['token']
                with client.websocket_connect(f'/ws?token={token}&device={device}&voice=true') as ws:
                    deadline=threading.Timer(10,ws.close)
                    deadline.start()
                    self.addCleanup(deadline.cancel)
                    ws.send_json({'type':'start'})
                    # Greeting can finish before prompt publication; wait for both.
                    prompt_seen=False
                    for _ in range(40):
                        message=ws.receive()
                        if 'text' not in message:
                            continue
                        event=json.loads(message['text'])
                        if event['type']=='audioEnd':
                            ws.send_json({'type':'playback_done','id':event['id']})
                        if event['type']=='prompt':
                            prompt_seen=True
                        if event['type']=='audioIdle' and prompt_seen:
                            break
                    else:
                        self.fail('No initial playback completion')
                    ws.send_bytes(b'\0\0')
                    for _ in range(40):
                        message=ws.receive()
                        if 'text' not in message:
                            continue
                        event=json.loads(message['text'])
                        if event['type']=='found':
                            break
                        if event['type']=='audioEnd':
                            ws.send_json({'type':'playback_done','id':event['id']})
                    else:
                        self.fail('PCM recognition never reached the controller')
                    attempts=client.app.state.pl.store.attempts_for('demo-margaret')
                    self.assertEqual(len(attempts),1)
                    self.assertEqual(attempts[0]['word_id'],'w-biscuit')
                    ws.send_json({'type':'stop'})
