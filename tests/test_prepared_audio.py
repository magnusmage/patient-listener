"""Real CPU DSP and cache contracts; synthetic signals only, no GPU or inference."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import wave

from patient_listener.config import Settings
from patient_listener.voice.processing import RATE,decode,normalize,stretch,prepare_hint,hint_profile
from patient_listener.voice.fixed_audio import FIXED_LINES,prepare_fixed
from patient_listener.store.sqlite_store import SqliteStore
from patient_listener.tools.seed import seed_all

HAVE_AUDIO=all(importlib.util.find_spec(name) for name in ('numpy','pyloudnorm','audiotsm'))


@unittest.skipUnless(HAVE_AUDIO,'Needs optional CPU audio-processing dependencies')
class ProcessingTests(unittest.TestCase):
    def tone(self,seconds=1,frequency=220,amplitude=.1):
        import numpy as np
        return (np.sin(2*np.pi*frequency*np.arange(round(RATE*seconds))/RATE)*amplitude*32767).astype('<i2').tobytes()

    def test_wsola_extends_duration_without_lowering_pitch(self):
        import numpy as np
        source=self.tone(seconds=2)
        result=stretch(source,.8)
        self.assertAlmostEqual(len(result)/len(source),1.25,places=3)
        signal=decode(result)
        frequency=np.fft.rfftfreq(len(signal),1/RATE)[np.argmax(np.abs(np.fft.rfft(signal)))]
        self.assertAlmostEqual(frequency,220,delta=2)
        self.assertGreater(np.sqrt(np.mean(signal[-2205:]**2)),.01)

    def test_lufs_normalization_preserves_safe_pcm(self):
        import numpy as np
        import pyloudnorm as pyln
        result=normalize(self.tone(amplitude=.4),-20)
        self.assertAlmostEqual(pyln.Meter(RATE).integrated_loudness(decode(result)),-20,delta=.05)
        self.assertLessEqual(float(np.max(np.abs(decode(result)))),.981)

    def test_two_hint_sentences_have_exact_half_second_gap(self):
        import numpy as np
        source=self.tone()
        result=prepare_hint([source,source],Settings())
        length=round(RATE/.8)
        samples=decode(result)
        self.assertEqual(len(samples),2*length+RATE//2)
        self.assertTrue(np.all(samples[length:length+RATE//2]==0))

    def test_short_clip_normalizes_without_padding_output(self):
        source=self.tone(seconds=.15)
        result=normalize(source)
        self.assertEqual(len(result),len(source))

    def test_normal_rate_fallback_keeps_gap_and_silence_is_rejected(self):
        source=self.tone()
        result=prepare_hint([source,source],Settings(hint_audio_rate=1.0))
        self.assertEqual(len(result),2*len(source)+RATE)
        with self.assertRaises(ValueError):normalize(b'\0\0'*RATE)
        with self.assertRaises(ValueError):stretch(source,.6)

    def test_model_sentence_renderer_applies_processing(self):
        from patient_listener.app.nemo_stream import render_hint
        runtime=SimpleNamespace(settings=Settings())
        with patch('patient_listener.app.nemo_stream.synthesize',return_value=self.tone()) as synth:
            result=render_hint(runtime,"It's kettle. Say it with me: kettle.")
        self.assertEqual(synth.call_count,2)
        self.assertGreater(len(result),len(self.tone())*2)

    def test_fixed_wav_override_is_checked_and_normalized(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'synthetic-backchannel.wav'
            with wave.open(str(path),'wb') as audio:
                audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(RATE)
                audio.writeframes(self.tone(seconds=.5))
            runtime=SimpleNamespace(settings=Settings(backchannel_clip_path=str(path)),fixed_clips={})
            with patch('patient_listener.app.nemo_stream.synthesize',return_value=self.tone()) as synth:
                self.assertEqual(prepare_fixed(runtime),len(FIXED_LINES))
            self.assertEqual(synth.call_count,len(FIXED_LINES)-1)
            self.assertEqual(len(runtime.fixed_clips['mm']),RATE)


class CacheTests(unittest.TestCase):
    def test_fixed_cache_is_published_only_after_full_preparation(self):
        runtime=SimpleNamespace(settings=Settings(),fixed_clips={'old':b'previous'})
        with patch('patient_listener.app.nemo_stream.synthesize',side_effect=[b'\1\0',RuntimeError('test')]):
            with self.assertRaises(RuntimeError):prepare_fixed(runtime)
        self.assertEqual(runtime.fixed_clips,{'old':b'previous'})
        with patch('patient_listener.app.nemo_stream.synthesize',return_value=b'\1\0') as synth:
            prepare_fixed(runtime)
        self.assertEqual(synth.call_args_list[0].args[1],'Mm-hmm.')
        self.assertEqual(set(runtime.fixed_clips),set(FIXED_LINES))

    def test_old_sqlite_audio_is_preserved_but_not_reused_as_processed(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'legacy.db'
            old=sqlite3.connect(path)
            old.execute('CREATE TABLE hint_audio(person_id TEXT NOT NULL,word_id TEXT NOT NULL,level INTEGER NOT NULL,text TEXT NOT NULL,model TEXT NOT NULL,voice TEXT NOT NULL,pcm BLOB NOT NULL,PRIMARY KEY(person_id,word_id,level))')
            old.execute('INSERT INTO hint_audio VALUES (?,?,?,?,?,?,?)',('demo-margaret','w-biscuit',1,'A pet.','m','v',b'\1\0'))
            old.commit();old.close()
            store=SqliteStore(str(path))
            try:
                seed_all(store)
                self.assertEqual(store.hint_audio('demo-margaret','w-biscuit',1,'A pet.','m','v'),b'\1\0')
                self.assertIsNone(store.hint_audio('demo-margaret','w-biscuit',1,'A pet.','m','v',profile=hint_profile(Settings())))
                self.assertIn('profile',{r[1] for r in store._db.execute('PRAGMA table_info(hint_audio)')})
            finally:store.close()

    def test_processing_profile_changes_with_rate_and_loudness(self):
        self.assertNotEqual(hint_profile(Settings()),hint_profile(Settings(hint_audio_rate=1.0)))
        self.assertNotEqual(hint_profile(Settings()),hint_profile(Settings(clip_lufs=-22)))
