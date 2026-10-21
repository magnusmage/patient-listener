"""Per-WebSocket development voice bridge: bounded input, queued output, playback ACKs.

Only one voice session is permitted per GPU worker until concurrency is measured. Control
messages remain responsive while GPU work executes in a worker thread. Cancelled GPU kernels
are allowed to finish, but their output cannot reach the browser after Stop/safety.
"""
from __future__ import annotations
import asyncio
import logging
import re


async def worker_call(fn, *args):
    task = asyncio.create_task(asyncio.to_thread(fn, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # Multiple cancellations must not release the GPU session while its worker still runs.
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        task.result()
        raise


def spoken_text(event):
    kind = event['type']
    if kind in {'greeting', 'prompt', 'reply', 'hint', 'whatIHeard'}:
        return event.get('text', '')
    if kind == 'backchannel': return 'mm'
    if kind == 'offerHint': return 'Want a hint?'
    if kind == 'confirm': return f"Did you say {event['word']}?"
    if kind == 'moveOn': return "Let's try another."
    if kind == 'restOffer': return 'Want a rest?'
    return ''


class VoiceConnection:
    def __init__(self, runtime, session, socket, send_json):
        self.runtime, self.session, self.socket = runtime, session, socket
        self.send_json = send_json
        self.input = asyncio.Queue(maxsize=64)
        self.output = asyncio.Queue(maxsize=16)
        self.closed = False
        self.busy = False
        self.sequence = 0
        self.waiting_id = None
        self.played = asyncio.Event()
        self.tasks = []
        self.decoder = None
        self.input_epoch = 0
        self.decoder_epoch = 0

    def _invoke(self, fn, *args):
        with self.runtime.gpu_lock:
            return fn(*args)

    def _audio_busy(self, busy):
        setter = getattr(self.session, 'set_audio_busy', None)
        if setter is not None:
            setter(busy)

    async def start(self):
        from .nemo_stream import NemoStream
        self.decoder = await worker_call(
            self._invoke, NemoStream, self.runtime, tuple(w.text for w in self.session.words),
            self.runtime.settings.boost_alpha,
        )
        self.tasks = [asyncio.create_task(self._listen()), asyncio.create_task(self._speak())]

    async def send(self, event):
        if self.closed: return
        if event['type'] in {'safety', 'ended'}:
            self.closed = True
            self._audio_busy(False)
            for task in self.tasks:
                if task is not asyncio.current_task(): task.cancel()
            self.played.set()
            self._drain(self.input); self._drain(self.output)
            await self.send_json(event)
            await self.socket.close(code=1000)
            return
        await self.send_json(event)
        text = spoken_text(event)
        if text:
            self._audio_busy(True)
            # Sentence-by-sentence synthesis. A bounded queue fails visibly instead of growing forever.
            for sentence in re.split(r'(?<=[.!?])\s+', text):
                self.output.put_nowait(sentence)

    @staticmethod
    def _drain(queue):
        while not queue.empty(): queue.get_nowait()

    def _set_playback(self, busy):
        if self.busy != busy:
            self.busy = busy
            self.input_epoch += 1
            self._drain(self.input)

    def _decode(self, frame, epoch):
        # Called under the GPU lock. Never carry echo/partial text into a listening turn.
        if self.decoder_epoch != epoch:
            self.decoder.reset_stream()
            self.decoder_epoch = epoch
        return self.decoder.feed(frame)

    async def frame(self, frame):
        if not self.closed:
            if len(frame) > 32768 or len(frame) % 2:
                raise ValueError('Invalid PCM16 frame')
            self.input.put_nowait((frame, self.input_epoch))

    def acknowledge(self, sequence):
        if sequence == self.waiting_id:
            self.played.set()

    async def _listen(self):
        try:
            while not self.closed:
                frame, epoch = await self.input.get()
                if epoch != self.input_epoch: continue
                events = await worker_call(self._invoke, self._decode, frame, epoch)
                if epoch != self.input_epoch: continue
                for event in events:
                    if self.closed: break
                    if self.busy:
                        # FR-04: playback input is control-only, never captions or answers.
                        if event.kind in {'partial', 'final'} and event.text.strip().lower().strip('.!?') == 'stop':
                            await self.session.handle({'type': 'stop'})
                            break
                        continue
                    if event.kind == 'speech':
                        await self.session.on_audio_speech()
                    elif event.kind == 'partial':
                        await self.session.on_audio_partial(event.text)
                    elif event.kind == 'final':
                        control = event.text.strip().lower().strip('.!?')
                        if control in {'stop', 'yes', 'no', 'help', 'done'}:
                            await self.session.handle({'type': control})
                        else:
                            await self.session.on_audio_final(event.text)
                    elif event.kind == 'silence':
                        await self.session.on_audio_silence()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logging.getLogger(__name__).error('Voice input failed: %s', type(exc).__name__)
            await self.fail('speech_input_failed')

    async def _speak(self):
        from .nemo_stream import synthesize
        try:
            while not self.closed:
                text = await self.output.get()
                self._set_playback(True)
                self.session._cancel_ticker()
                self._drain(self.input)
                self.sequence += 1
                self.waiting_id = self.sequence
                self.played.clear()
                await self.send_json({'type': 'audioStart', 'id': self.sequence,
                                      'sample_rate': 22050, 'encoding': 'pcm_s16le'})
                pcm = await worker_call(self._invoke, synthesize, self.runtime, text)
                if self.closed: break
                await self.socket.send_bytes(pcm)
                await self.send_json({'type': 'audioEnd', 'id': self.sequence})
                await asyncio.wait_for(self.played.wait(), timeout=60)
                self.waiting_id = None
                if self.output.empty():
                    self._set_playback(False)
                    self._audio_busy(False)
                    await self.send_json({'type': 'audioIdle'})
                    await self.session.on_audio_silence()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logging.getLogger(__name__).error('Voice output failed: %s', type(exc).__name__)
            await self.fail('speech_output_failed')

    async def fail(self, code):
        self.closed = True
        self.session.close()
        self._drain(self.input); self._drain(self.output)
        await self.send_json({'type': 'voiceError', 'code': code})
        await self.socket.close(code=1011)

    async def close(self):
        self.closed = True
        self._audio_busy(False)
        self.played.set()
        for task in self.tasks: task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self._drain(self.input); self._drain(self.output)
        self.decoder = None
