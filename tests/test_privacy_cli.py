"""CLI does not send deletion without explicit typed confirmation."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from patient_listener.tools.privacy import main


class PrivacyCliTests(unittest.TestCase):
    def run_cli(self, args, replies, inputs):
        opener = MagicMock()
        responses = []
        for reply in replies:
            response = MagicMock()
            response.__enter__.return_value.read.return_value = reply
            responses.append(response)
        opener.open.side_effect = responses
        with patch('patient_listener.tools.privacy.build_opener', return_value=opener), \
             patch('patient_listener.tools.privacy.getpass.getpass', return_value='synthetic-console-token'), \
             patch('builtins.input', side_effect=inputs), patch('sys.stdout', new_callable=io.StringIO):
            result = main(args)
        return result, opener

    def test_export_writes_new_file_after_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'export.csv'
            result, opener = self.run_cli(['export', '--person', 'test-person', '--out', str(path)], [b'type,text\nphrase,Hello\n'], ['YES'])
            self.assertEqual(result, 0)
            self.assertIn('Hello', path.read_text())
            request = opener.open.call_args.args[0]
            self.assertEqual(json.loads(request.data), {'personConfirmed': True})
            self.assertEqual(request.method, 'POST')

    def test_cancelled_deletion_only_requests_challenge(self):
        challenge = json.dumps({'person_id':'test-person', 'retained_records':'consent evidence retained', 'confirmation_token':'x'*43}).encode()
        result, opener = self.run_cli(['delete', '--person', 'test-person'], [challenge], ['no'])
        self.assertEqual(result, 0)
        self.assertEqual(opener.open.call_count, 1)
        self.assertTrue(opener.open.call_args.args[0].full_url.endswith('/deletion-request'))

    def test_confirmed_deletion_uses_challenge_without_exposing_token_in_url(self):
        challenge = json.dumps({'person_id':'test-person', 'retained_records':'consent evidence retained', 'confirmation_token':'x'*43}).encode()
        result, opener = self.run_cli(['delete', '--person', 'test-person'], [challenge, b'{"deleted":true}'], ['DELETE test-person'])
        self.assertEqual(result, 0)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.method, 'DELETE')
        self.assertNotIn('x'*43, request.full_url)
        self.assertEqual(json.loads(request.data)['confirmationToken'], 'x'*43)
