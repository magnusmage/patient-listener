"""FR-13: actual voiced PCM, five explicit phrases, privacy and safety. No GPU/models."""
import asyncio
from array import array
from contextlib import nullcontext
import json
import math
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from patient_listener.app.session import AppSession
from patient_listener.app.audio import AsrEvent
from patient_listener.app.voice_connection import VoiceConnection
from patient_listener.store.sqlite_store import SqliteStore
from patient_listener.tools.seed import seed_all
from patient_listener.voice.loudness import SessionLoudness, VoicedLevel

SETTINGS = {'type':'audio_settings', 'auto_gain_control':False,
            'noise_suppression':False, 'echo_cancellation':False, 'safari':False, 'changed':False}


class PcmTests(unittest.TestCase):
    def test_pcm_scaling_and_boundary(self):
        level = VoicedLevel()
        level.add([0.1] * 1600)
        self.assertAlmostEqual(level.level(), -20, places=5)
        for delta, strong in ((-1,True),(-2,False),(-3,False),(0,True)):
            meter = SessionLoudness()
            for _ in range(5):
                meter.observe(-20, 1600); self.assertTrue(meter.accept_phrase())
            measured = VoicedLevel()
            measured.add([0.1 * 10 ** (delta / 20)] * 1600)
            result = meter.feedback(measured.level())
            self.assertEqual(result['strong'], strong)
            self.assertNotIn('db', json.dumps(result).lower())

    def test_calibration_median_and_segment_weights(self):
        meter = SessionLoudness()
        self.assertFalse(meter.accept_phrase())
        for db in (-20,-24,-22,-26,-23):
            meter.observe(db, 1600); meter.accept_phrase()
        self.assertEqual(meter.baseline, -23)
        self.assertFalse(meter.accept_phrase())
        weighted = SessionLoudness()
        weighted.observe(-20,1600); weighted.observe(-30,3200); weighted.accept_phrase()
        self.assertAlmostEqual(weighted.phrases[0],10*math.log10((.01+2*.001)/3))

    def test_empty_short_and_nonfinite_samples_are_not_valid_phrases(self):
        level = VoicedLevel()
        self.assertIsNone(level.level())
        level.add([.1]*512); self.assertIsNone(level.level())
        with self.assertRaises(ValueError):level.add([float('nan')])
        meter = SessionLoudness()
        for value,count in ((float('nan'),1600),(-20,0),(-20,100),(-200,1600)):
            self.assertFalse(meter.observe(value,count))
        self.assertFalse(meter.accept_phrase())

    def test_nemo_uses_only_vad_positive_frames_even_without_transcription(self):
        class Samples(list):
            def astype(self, kind): return self
            def __truediv__(self, value): return Samples(x / value for x in self)
            def __getitem__(self, key):
                value = super().__getitem__(key)
                return Samples(value) if isinstance(key, slice) else value
            def copy(self): return Samples(self)
        np = SimpleNamespace(frombuffer=lambda data, dtype: Samples(array('h', data)))
        from patient_listener.app.nemo_stream import NemoStream
        decoder = NemoStream.__new__(NemoStream)
        decoder.np = np
        decoder.torch = SimpleNamespace(inference_mode=nullcontext,from_numpy=lambda v:v)
        scores = iter([1,1,1,1,1]+[0]*20)
        decoder.vad = lambda *args:next(scores)
        decoder.pending=bytearray();decoder.speaking=False;decoder.quiet_samples=0
        decoder.segment_samples=0;decoder.text='';decoder.level=VoicedLevel()
        decoder.decode=lambda samples:''
        decoder.reset_decoder=lambda:None
        voice=array('h',[3277]*2560).tobytes()
        # High-amplitude non-speech must not change measured voice RMS.
        noise=array('h',[30000]*2560).tobytes()
        events=decoder.feed(voice)
        for _ in range(4):events+=decoder.feed(noise)
        final=next(e for e in events if e.kind=='final')
        self.assertEqual(final.text,'')
        self.assertEqual(final.voiced_samples,2560)
        self.assertAlmostEqual(final.level_db,-20,places=2)


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store=SqliteStore(check_same_thread=False,ai_enabled=False)
        seed_all(self.store)
        self.events=[]
        async def send(event):self.events.append(event)
        self.session=AppSession(self.store,'demo-joseph',send)

    async def asyncTearDown(self):
        self.session.close()
        await asyncio.sleep(0)
        self.store.close()

    async def start(self):
        await self.session.handle(SETTINGS)
        await self.session.start()

    async def calibrate(self):
        await self.start()
        for db in (-20,-24,-22,-26,-23):
            await self.session.on_audio_level(db,2560)
            await self.session.handle({'type':'calibration_next'})

    async def test_five_phrases_require_explicit_taps_and_no_practice_turns(self):
        await self.start()
        self.assertTrue(self.session.calibrating)
        for _ in range(5):await self.session.on_audio_level(-23,2560)
        self.assertEqual(self.session.loudness.phrases,[])
        self.assertEqual(self.session.engine.controller.turns,0)
        await self.session.handle({'type':'calibration_next'})
        self.assertEqual(len(self.session.loudness.phrases),1)
        for db in (-24,-22,-26,-20):
            await self.session.on_audio_level(db,2560)
            await self.session.handle({'type':'calibration_next'})
        self.assertFalse(self.session.calibrating)
        self.assertEqual(self.session.loudness.baseline,-23)
        self.assertEqual(self.session.engine.controller.turns,1)
        self.assertFalse(self.store.attempts_for('demo-joseph'))

    async def test_typed_text_and_silence_cannot_calibrate_or_fake_a_level(self):
        await self.start()
        await self.session.handle({'type':'typed','text':'Good morning.'})
        await self.session.on_audio_silence()
        await self.session.handle({'type':'calibration_next'})
        self.assertEqual(self.session.loudness.phrases,[])
        self.assertIsNone(self.session._ticker)
        self.assertFalse(any(e['type']=='loudness' for e in self.events))
        await self.session.handle({'type':'loudness','level_db':-20})
        self.assertFalse(self.session.loudness.pending_count)

    async def test_measurement_drives_relative_feedback_without_numbers(self):
        await self.calibrate()
        self.events.clear()
        await self.session.on_audio_level(-24,2560)
        await self.session.on_audio_level(-25,2560)
        await self.session.on_audio_level(-26,2560)
        levels=[e for e in self.events if e['type']=='loudness']
        self.assertEqual([e['strong'] for e in levels],[True,False,False])
        self.assertGreater(levels[0]['position'],levels[-1]['position'])
        self.assertEqual([e['text'] for e in self.events if e['type']=='reply'],['A bit stronger?']*2)
        self.assertNotIn('baseline',json.dumps(self.events))
        self.assertNotIn('level_db',json.dumps(self.events))

    async def test_settings_change_requires_a_new_session_baseline(self):
        await self.calibrate()
        await self.session.handle({**SETTINGS,'changed':True})
        self.assertTrue(self.session.calibrating)
        self.assertIsNone(self.session.loudness.baseline)
        self.assertEqual(self.session.loudness.phrases,[])

    async def test_unverified_processing_does_not_produce_a_measurement(self):
        await self.session.handle({**SETTINGS,'auto_gain_control':True})
        await self.session.start()
        await self.session.on_audio_level(-20,2560)
        self.assertFalse(self.session.calibrating)
        self.assertFalse(any(e['type']=='loudness' for e in self.events))
        self.assertIn('unavailable',next(e for e in self.events if e['type']=='prompt')['instruction'])

    async def test_safari_exception_and_other_profiles(self):
        await self.session.handle({**SETTINGS,'safari':True,'echo_cancellation':True})
        await self.session.start()
        self.assertTrue(self.session.calibrating)
        self.session.close()
        async def send(event):self.events.append(event)
        self.session=AppSession(self.store,'demo-margaret',send)
        await self.session.handle(SETTINGS)
        await self.session.start()
        self.assertFalse(self.session.calibrating)

    async def test_safety_stops_during_calibration_and_ignores_late_levels(self):
        await self.start()
        await self.session.on_audio_final('my arm feels funny and words are worse today')
        self.assertTrue(self.session.ended)
        await self.session.on_audio_level(-20,2560)
        self.assertEqual(self.session.loudness.phrases,[])
        self.assertTrue(any(e['type']=='safety' for e in self.events))

    async def test_stop_and_playback_discard_levels_and_close_drops_baseline(self):
        await self.start()
        self.session.set_audio_busy(True)
        await self.session.on_audio_level(-20,2560)
        self.assertEqual(self.session.loudness.pending_count,0)
        self.session.set_audio_busy(False)
        await self.session.stop()
        await self.session.on_audio_level(-20,2560)
        self.assertEqual(self.session.loudness.pending_count,0)
        self.session.close()
        self.assertIsNone(self.session.loudness.baseline)

    async def test_hoarseness_pauses_loudness_during_setup(self):
        await self.start()
        await self.session.on_audio_final('my voice has been hoarse for three weeks')
        self.assertTrue(self.session.ended)
        await self.session.on_audio_level(-20,2560)
        self.assertEqual(self.session.loudness.pending_count,0)

    async def test_settings_change_does_not_block_playback_ack_reader(self):
        await self.calibrate()
        self.session.set_audio_busy(True)
        await asyncio.wait_for(self.session.handle({**SETTINGS,'changed':True}),.2)
        self.assertTrue(self.session.calibrating)
        self.session.set_audio_busy(False)
        await asyncio.sleep(0)
        self.assertTrue(self.events[-2]['calibration'])

    async def test_loudness_does_not_override_word_matching(self):
        self.store.add_word_draft('j-word','demo-joseph','kettle','object',added_by='slt')
        self.store.approve_word('j-word',by='slt')
        # Rebuild to pick up the approved target.
        self.session.close()
        async def send(event):self.events.append(event)
        self.session=AppSession(self.store,'demo-joseph',send)
        await self.calibrate()
        await self.session.on_audio_final('kettle')
        await self.session.on_audio_level(-30,2560)
        attempts=self.store.attempts_for('demo-joseph')
        self.assertEqual(len(attempts),1)
        self.assertEqual(attempts[0]['outcome'],'found')

    async def test_combined_being_clear_still_requires_the_check_tap(self):
        from patient_listener.types import Need
        self.store.add_person('combined','Demo',frozenset({Need.BEING_HEARD,Need.BEING_CLEAR}))
        self.store.add_word_draft('combined-word','combined','kettle','object',added_by='slt')
        self.store.approve_word('combined-word',by='slt')
        self.session.close()
        async def send(event):self.events.append(event)
        self.session=AppSession(self.store,'combined',send)
        await self.calibrate()
        await self.session.on_audio_final('kettle')
        await self.session.on_audio_level(-30,2560)
        self.assertTrue(any(e['type']=='whatIHeard' for e in self.events))
        await self.session.handle({'type':'yes'})
        self.assertFalse(self.store.attempts_for('combined'))
        await self.session.handle({'type':'confirm_tap','ok':True})
        self.assertEqual(len(self.store.attempts_for('combined')),1)

    async def test_person_can_skip_meter_and_type_without_fake_feedback(self):
        await self.start()
        await self.session.handle({'type':'calibration_skip'})
        self.assertFalse(self.session.calibrating)
        self.events.clear()
        await self.session.handle({'type':'typed','text':'Good morning.'})
        await self.session.on_audio_level(-20,2560)
        self.assertFalse(any(e['type']=='loudness' for e in self.events))
