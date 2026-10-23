"""Pipecat 1.12 frames for the authenticated NeMo/Magpie voice path.

Direct-mode processors preserve the existing bounded input/output workers and let
Stop/capture run while synthesis is pending. No aggregator or automatic turn strategy
is installed: the patience controller remains the sole owner of speaking decisions.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import version
import logging

from pipecat.frames.frames import (
    InputAudioRawFrame, TTSAudioRawFrame, TextFrame, TranscriptionFrame,
    InterimTranscriptionFrame, VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame,
    UserSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.workers.runner import WorkerRunner


VERSION = '1.12.0'
SYNTHESIS_STALL_S = 5.0


def require_pipecat():
    installed = version('pipecat-ai')
    if installed != VERSION:
        raise RuntimeError('Install pipecat-ai==1.12.0 for the verified voice pipeline')
    return installed


class _PrivateFrame:
    def __str__(self):
        return f'{self.name}(content redacted)'

    def __repr__(self):
        return str(self)


class MicrophoneFrame(_PrivateFrame, InputAudioRawFrame):
    pass


class PartialFrame(_PrivateFrame, InterimTranscriptionFrame):
    pass


class FinalFrame(_PrivateFrame, TranscriptionFrame):
    pass


class SpeechFrame(_PrivateFrame, TextFrame):
    pass


class PlaybackFrame(_PrivateFrame, TTSAudioRawFrame):
    pass


@dataclass
class _Request:
    completed: bool = False
    error: str = ''


class _Processor(FrameProcessor):
    def __init__(self, owner, name):
        super().__init__(name=name, enable_direct_mode=True)
        self.owner = owner

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        request = frame.metadata.get('request')
        if request is None or direction != FrameDirection.DOWNSTREAM:
            await self.push_frame(frame, direction)
            return
        try:
            await self.patient_frame(frame, direction)
        except Exception as exc:
            logging.getLogger('uvicorn.error.patient_listener.voice').error(
                'Voice pipeline stage failed stage=%s error_type=%s', self.name, type(exc).__name__)
            # Do not let framework exception logging include model errors/transcripts.
            request.error = 'voice_frame_failed'

    async def patient_frame(self, frame, direction):
        await self.push_frame(frame, direction)


class NeMoInput(_Processor):
    def __init__(self, owner, name):
        super().__init__(owner, name)
        self.speech_active = False
        self.capture_epoch = None

    async def patient_frame(self, frame, direction):
        if not isinstance(frame, MicrophoneFrame):
            await self.push_frame(frame, direction)
            return
        request = frame.metadata['request']
        connection = self.owner.connection
        epoch = frame.metadata['epoch']
        if self.capture_epoch != epoch:
            self.capture_epoch = epoch
            self.speech_active = False
        if frame.sample_rate != 16000 or frame.num_channels != 1:
            raise ValueError('Expected mono 16 kHz input')
        if connection.closed or epoch != connection.input_epoch:
            request.completed = True
            return
        from .voice_connection import worker_call
        events = await worker_call(connection._invoke, connection._decode, frame.audio, epoch)
        for event in events:
            if connection.closed or epoch != connection.input_epoch or request.error:
                break
            if event.kind == 'speech':
                speech = UserSpeakingFrame() if self.speech_active else VADUserStartedSpeakingFrame()
                self.speech_active = True
            elif event.kind == 'silence':
                speech = VADUserStoppedSpeakingFrame()
                self.speech_active = False
            elif event.kind == 'partial':
                speech = PartialFrame(text=event.text, user_id='', timestamp=datetime.now(timezone.utc).isoformat())
            elif event.kind == 'final':
                speech = FinalFrame(text=event.text, user_id='', timestamp=datetime.now(timezone.utc).isoformat())
            else:
                raise ValueError('Unknown recognition event')
            speech.metadata.update(request=request, epoch=epoch, event=event)
            await self.push_frame(speech, direction)
        request.completed = True


class Patience(_Processor):
    async def patient_frame(self, frame, direction):
        event = frame.metadata.get('event')
        if event is None:
            await self.push_frame(frame, direction)
        else:
            connection = self.owner.connection
            if not connection.closed and frame.metadata['epoch'] == connection.input_epoch:
                await connection._dispatch_event(event)


class MagpieOutput(_Processor):
    async def patient_frame(self, frame, direction):
        if not isinstance(frame, SpeechFrame):
            await self.push_frame(frame, direction)
            return
        connection = self.owner.connection
        request = frame.metadata['request']
        if connection.closed:
            request.completed = True
            return
        cached = frame.metadata['cached']
        from .voice_connection import worker_call
        from .nemo_stream import synthesize
        pcm = cached if cached is not None else await worker_call(
            connection._invoke, synthesize, connection.runtime, frame.text)
        if connection.closed:
            request.completed = True
            return
        if not isinstance(pcm, bytes) or not pcm or len(pcm) % 2:
            raise ValueError('Expected nonempty PCM16 output')
        audio = PlaybackFrame(audio=pcm, sample_rate=22050, num_channels=1)
        audio.metadata['request'] = request
        await self.push_frame(audio, direction)


class BrowserOutput(_Processor):
    async def patient_frame(self, frame, direction):
        if not isinstance(frame, PlaybackFrame):
            await self.push_frame(frame, direction)
            return
        if frame.sample_rate != 22050 or frame.num_channels != 1:
            raise ValueError('Expected mono 22.05 kHz output')
        if not self.owner.connection.closed:
            await self.owner.connection.socket.send_bytes(frame.audio)
        frame.metadata['request'].completed = True


class PipecatVoicePipeline:
    def __init__(self, connection):
        self.version = require_pipecat()
        self.connection = connection
        self.ready = asyncio.Event()
        self.stopping = False
        self.task = None
        self.processors = [NeMoInput(self, 'NeMoVAD_ASR'), Patience(self, 'PatienceController'),
                           MagpieOutput(self, 'MagpieTTS'), BrowserOutput(self, 'BrowserPCM')]
        self.pipeline = Pipeline(self.processors)
        self.worker = PipelineWorker(self.pipeline,
            params=PipelineParams(audio_in_sample_rate=16000, audio_out_sample_rate=22050,
                                  enable_metrics=False, enable_usage_metrics=False,
                                  enable_heartbeats=False, send_initial_empty_metrics=False),
            enable_rtvi=False, enable_tracing=False, enable_turn_tracking=False,
            idle_timeout_secs=None, cancel_on_idle_timeout=False)
        self.runner = WorkerRunner(handle_sigint=False, handle_sigterm=False)

        @self.worker.event_handler('on_pipeline_started')
        async def started(worker, frame):
            self.ready.set()

    async def start(self):
        await self.runner.add_workers(self.worker)
        self.task = asyncio.create_task(self.runner.run(), name='patient-pipecat')
        ready = asyncio.create_task(self.ready.wait())
        try:
            done, _ = await asyncio.wait([ready, self.task], timeout=10,
                                         return_when=asyncio.FIRST_COMPLETED)
            if ready not in done or self.task.done():
                raise RuntimeError('Pipecat voice pipeline did not start')
        finally:
            ready.cancel()
            await asyncio.gather(ready, return_exceptions=True)
        self.task.add_done_callback(self._finished)
        logging.getLogger('uvicorn.error.patient_listener.voice').info(
            'Voice pipeline started framework=pipecat version=%s input_hz=16000 output_hz=22050',
            self.version)

    def _finished(self, task):
        if not self.stopping and not self.connection.closed:
            asyncio.create_task(self.connection.fail('voice_pipeline_failed'))

    async def _process(self, frame):
        if not self.ready.is_set() or self.stopping:
            raise RuntimeError('Pipecat pipeline is not running')
        request = _Request()
        frame.metadata['request'] = request
        await self.pipeline.queue_frame(frame)
        if request.error or (not request.completed and not self.connection.closed):
            raise RuntimeError('Voice frame processing failed')

    async def receive(self, pcm, epoch):
        frame = MicrophoneFrame(audio=pcm, sample_rate=16000, num_channels=1)
        frame.metadata['epoch'] = epoch
        await self._process(frame)

    async def speak(self, text, cached):
        frame = SpeechFrame(text=text)
        frame.metadata['cached'] = cached
        watchdog = None
        if cached is None:
            async def stalled():
                await asyncio.sleep(SYNTHESIS_STALL_S)
                if not self.connection.closed:
                    await self.connection.fail('speech_output_stalled')
            watchdog = asyncio.create_task(stalled())
        try:
            await self._process(frame)
        finally:
            if watchdog is not None:
                watchdog.cancel()
                await asyncio.gather(watchdog, return_exceptions=True)

    async def close(self):
        self.stopping = True
        if self.task is not None:
            await self.worker.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
