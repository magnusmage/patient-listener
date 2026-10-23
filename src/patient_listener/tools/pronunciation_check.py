"""Offline matching/pronunciation readiness check. No API keys or model calls."""
import argparse
from importlib.metadata import version
import json
import shutil


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--word', action='append', dest='words')
    parser.add_argument('--require-epitran', action='store_true',
                        help='Fail unless the real English fallback can run')
    args = parser.parse_args(argv)
    from ..text.phonetics import first_sound, _dictionary, _epitran, _ipa_first
    from ..voice.hints import sound_line
    report = {'versions': {name: version(name) for name in
                           ('rapidfuzz', 'jellyfish', 'nltk', 'epitran')},
              'lex_lookup_available': bool(shutil.which('lex_lookup')), 'words': []}
    failed = False
    try:
        report['cmudict_words'] = len(_dictionary())
    except Exception as exc:
        report['cmudict_error'] = str(exc)
        failed = True
    if args.require_epitran:
        try:
            report['epitran_test_first_sound'] = _ipa_first(_epitran().transliterate('Farida'))
        except Exception as exc:
            report['epitran_error'] = str(exc)
            failed = True
    for word in args.words or ['knife', 'phone', 'chair', 'kettle']:
        try:
            phone = first_sound(word)
            report['words'].append({'word': word, 'first_sound': phone, 'hint': sound_line(phone)})
        except Exception as exc:
            report['words'].append({'word': word, 'error': str(exc)})
            failed = True
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
