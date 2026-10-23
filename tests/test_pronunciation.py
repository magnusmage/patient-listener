"""Real library matching, dictionary integration and unavailable-resource behavior."""
from contextlib import redirect_stdout
from io import StringIO
import json
import subprocess
import unittest
from unittest.mock import Mock, patch

from patient_listener.text import phonetics
from patient_listener.voice.matcher import best_match, score
from patient_listener.voice.hints import sound_line, template_hint_lines
from patient_listener.schemas import WordEntry


class PronunciationTests(unittest.TestCase):
    def test_real_cmudict_handles_silent_letters_and_digraphs(self):
        for word, expected in [('knife','N'), ('phone','F'), ('chair','CH'),
                               ('hour','AW'), ('one','W'), ('Café','K'), ('apple','AE')]:
            with self.subTest(word=word):
                self.assertEqual(phonetics.first_sound(word), expected)
        self.assertEqual(phonetics.first_sound('Can you open the window?'), 'K')

    def test_first_sound_derivation_is_off_the_matching_path(self):
        with patch.object(phonetics, '_dictionary', side_effect=AssertionError('no lookup')):
            self.assertEqual(score('kettle', 'kettle'), 1)

    def test_unknown_name_calls_epitran_and_maps_whole_ipa_segments(self):
        for ipa, phone in [('ˈfaɹida','F'), ('t͡ʃina','CH'), ('d͡ʒana','JH'), ('eɪna','EY')]:
            converter = Mock()
            converter.transliterate.return_value = ipa
            with patch.object(phonetics, '_dictionary', return_value={}), \
                 patch.object(phonetics, '_epitran', return_value=converter):
                self.assertEqual(phonetics.first_sound('Zorvella'), phone)
                converter.transliterate.assert_called_once_with('zorvella')

    def test_missing_or_failed_resources_do_not_guess_a_letter(self):
        with patch.object(phonetics, '_dictionary', return_value={}), \
             patch.object(phonetics, '_epitran', side_effect=phonetics.PronunciationUnavailable('setup')):
            with self.assertRaises(phonetics.PronunciationUnavailable):
                phonetics.first_sound('Zorvella')
        with self.assertRaises(phonetics.PronunciationError):
            phonetics.first_sound('123 !!!')
        converter = Mock()
        converter.transliterate.return_value = ''
        with patch.object(phonetics, '_dictionary', return_value={}), \
             patch.object(phonetics, '_epitran', return_value=converter):
            with self.assertRaises(phonetics.PronunciationError):
                phonetics.first_sound('Zorvella')

    def test_english_subprocess_has_timeout_and_uses_no_shell(self):
        from types import SimpleNamespace
        import epitran
        from epitran.flite import FliteLexLookup
        phonetics._epitran.cache_clear()
        try:
            with patch.object(phonetics.shutil, 'which', return_value='/test/lex_lookup'), \
                 patch.object(epitran, 'Epitran', return_value=SimpleNamespace()), \
                 patch.object(FliteLexLookup, '__init__', return_value=None), \
                 patch.object(phonetics.subprocess, 'run',
                              side_effect=subprocess.TimeoutExpired('lex_lookup', 2)) as run:
                converter = phonetics._epitran()
                with self.assertRaises(subprocess.TimeoutExpired):
                    converter.epi.english_g2p('Name')
                self.assertEqual(run.call_args.args[0], ['lex_lookup','name'])
                self.assertEqual(run.call_args.kwargs['timeout'], 2)
                self.assertNotIn('shell', run.call_args.kwargs)
        finally:
            phonetics._epitran.cache_clear()

    def test_sound_hint_uses_phoneme_not_spelling_or_raw_arpabet(self):
        for phone, expected in [('N','It starts with N.'), ('CH','It starts with the ch sound.'),
                                ('HH','It starts with H.'), ('AE','It starts with the a sound.')]:
            self.assertEqual(sound_line(phone), expected)
        self.assertEqual(sound_line(''), 'Listen for the first sound.')
        word = WordEntry('w','p','knife','object',first_sound='N')
        self.assertEqual(template_hint_lines(word).sound, 'It starts with N.')

    def test_exact_libraries_and_empty_inputs(self):
        from patient_listener.text.fuzzy import ratio
        import jellyfish
        self.assertEqual(ratio('tide','diet'), 50)
        for text in ('knight', 'phone', 'Biscuit', 'Leah', ''):
            self.assertEqual(phonetics.metaphone(text), jellyfish.metaphone(text))
        for heard, target in [('', ''), ('!!!','???'), ('123','123'), ('','Leo'), ('!!!!!!!!!!','!!!!!!!!!!a')]:
            self.assertEqual(score(heard, target), 0)
        self.assertIsNone(best_match([''], [WordEntry('w','p','Leo','person')]))

    def test_readiness_command_needs_no_models(self):
        from patient_listener.tools.pronunciation_check import main
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['--word','knife']), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result['words'][0]['first_sound'], 'N')
        self.assertGreater(result['cmudict_words'], 100000)

    def test_manual_sound_is_preserved_and_automatic_sound_is_stored(self):
        from patient_listener.store.sqlite_store import SqliteStore
        from patient_listener.types import WordStatus
        store = SqliteStore()
        try:
            store.add_person('p','Test',frozenset())
            derived = store.add_word_draft('one','p','knife','object')
            manual = store.add_word_draft('two','p','Zorvella','person',first_sound='Z')
            self.assertEqual(derived.first_sound, 'N')
            self.assertEqual(derived.status, WordStatus.DRAFT)
            self.assertEqual(manual.first_sound, 'Z')
        finally:
            store.close()
