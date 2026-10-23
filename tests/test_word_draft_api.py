"""Authenticated draft creation, approval, persistence and judge isolation."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
    from patient_listener.app.server import create_app
    from patient_listener.config import Settings
    HAVE_API = True
except ImportError:
    HAVE_API = False


def config(**kwargs):
    return Settings(ai_enabled=False, nebius_api_key='', voice_enabled=False, **kwargs)


@unittest.skipUnless(HAVE_API, 'needs api extra')
class WordDraftApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app(config(console_demo_enabled=False)))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.store = self.client.app.state.pl.store
        self.slt = self.identity('sam', 'therapist', 'demo-margaret')
        self.carer = self.identity('alex', 'carer', 'demo-margaret')
        self.payload = {'text':'Rex', 'kind':'person', 'meaning_cue':'a family pet', 'first_sound':'R'}

    def identity(self, user, role, person=None):
        self.store.set_console_user(user, user, role)
        if person: self.store.link_console_user(user, person)
        return {'Authorization':'Bearer '+self.store.issue_console_token(user)}

    def create(self, headers=None, payload=None, person='margaret'):
        return self.client.post('/api/console/words/'+person,
            headers=headers if headers is not None else self.carer,
            json=payload if payload is not None else self.payload)

    def test_carer_draft_is_saved_but_not_practised_until_therapist_approval(self):
        response = self.create()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        word = response.json()['word']
        self.assertEqual((word['status'],word['by']), ('draft','carer'))
        self.assertTrue(word['id'].startswith('w-'))
        self.assertNotIn(word['id'], {w.id for w in self.store.words('demo-margaret')})
        saved = self.client.get('/api/console/words/margaret',headers=self.carer).json()['words']
        self.assertIn(word, saved)
        audit = self.store.audit_log()[-1]
        self.assertEqual(audit['actor'], 'alex')
        self.assertIn(word['id'], audit['detail'])
        self.assertNotIn('Rex', audit['detail'])
        path='/api/console/words/margaret/'+word['id']+'/approve'
        self.assertEqual(self.client.post(path,headers=self.carer).status_code,403)
        self.assertEqual(self.client.post(path,headers=self.slt).status_code,200)
        self.assertIn(word['id'], {w.id for w in self.store.words('demo-margaret')})

    def test_therapist_creation_also_starts_as_draft(self):
        response=self.create(headers=self.slt)
        self.assertEqual(response.status_code,201)
        self.assertEqual(response.json()['word']['status'],'draft')
        self.assertEqual(response.json()['word']['by'],'slt')
        self.assertEqual(self.store.audit_log()[-1]['actor'],'sam')

    def test_authentication_and_role_are_required(self):
        patient_token=self.client.get('/api/session',headers={'X-PL-Device':'a'*48}).json()['token']
        for headers in ({}, {'Authorization':'Bearer fake'}, {'Authorization':'Bearer '+patient_token}):
            with self.subTest(headers=list(headers)):
                self.assertEqual(self.create(headers=headers).status_code,401)
        for role in ('agent','patient'):
            headers=self.identity(role,role,'demo-margaret')
            self.assertEqual(self.create(headers=headers).status_code,403)

    def test_linked_patient_scope_applies_to_alias_and_full_id(self):
        headers=self.identity('other','carer','demo-joseph')
        for person in ('margaret','demo-margaret','nobody'):
            self.assertEqual(self.create(headers=headers,person=person).status_code,404)

    def test_cannot_supply_identity_status_or_overwrite_existing_word(self):
        before=len(self.store.all_words('demo-margaret'))
        for field,value in {'id':'w-leo','status':'approved','added_by':'slt',
                            'approved_by':'sam','person_id':'demo-joseph','role':'therapist'}.items():
            with self.subTest(field=field):
                self.assertEqual(self.create(payload={**self.payload,field:value}).status_code,422)
        self.assertEqual(len(self.store.all_words('demo-margaret')),before)
        self.assertEqual(self.store._read_word('w-leo').text,'Leo')

    def test_invalid_values_do_not_write_rows(self):
        before=len(self.store.all_words('demo-margaret'))
        invalid=[{'text':''},{'text':'  '},{'text':'x'*61},{'text':12},{'kind':'diagnosis'},
                 {'kind':None},{'meaning_cue':'x'*91},{'first_sound':'x'*5},
                 {'meaning_cue':False},{'text':'a\nb'}]
        for change in invalid:
            with self.subTest(change=change):
                self.assertEqual(self.create(payload={**self.payload,**change}).status_code,422)
        self.assertEqual(len(self.store.all_words('demo-margaret')),before)

    def test_automatic_phoneme_and_setup_errors(self):
        from unittest.mock import patch
        from patient_listener.text.phonetics import PronunciationError, PronunciationUnavailable
        result = self.create(payload={'text':'knife','kind':'object'})
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.json()['word']['first'], 'N')
        before = len(self.store.all_words('demo-margaret'))
        for error, status in [(PronunciationUnavailable('Install pronunciation assets'), 503),
                              (PronunciationError('Supply first_sound explicitly'), 422)]:
            with patch('patient_listener.text.phonetics.first_sound', side_effect=error):
                response = self.create(payload={'text':'Zorvella','kind':'person'})
                self.assertEqual(response.status_code, status)
        self.assertEqual(len(self.store.all_words('demo-margaret')), before)

    def test_unicode_trim_phrase_limit_and_distinct_ids(self):
        first=self.create(payload={'text':'  Café  ','kind':'place'})
        self.assertEqual(first.status_code,201)
        self.assertEqual(first.json()['word']['text'],'Café')
        self.assertEqual(first.json()['word']['first'],'K')
        second=self.create(payload={'text':'x'*60,'kind':'phrase','first_sound':'X'},person='demo-margaret')
        self.assertEqual(second.status_code,201)
        self.assertNotEqual(first.json()['word']['id'],second.json()['word']['id'])

    def test_carer_without_therapist_can_approve_the_saved_draft(self):
        self.store._db.execute("DELETE FROM console_links WHERE user_id='sam'")
        self.store._db.commit()
        word=self.create().json()['word']
        path='/api/console/words/margaret/'+word['id']+'/approve'
        self.assertEqual(self.client.post(path,headers=self.carer).status_code,200)

    def test_store_boundary_rejects_unlinked_or_agent_actor(self):
        self.identity('unlinked','carer')
        self.identity('agent','agent','demo-margaret')
        for actor in ('unlinked','agent','unknown'):
            with self.subTest(actor=actor),self.assertRaises(PermissionError):
                self.store.console_add_word_draft('demo-margaret',actor=actor,text='Rex',kind='person')


@unittest.skipUnless(HAVE_API,'needs api extra')
class DraftPersistenceTests(unittest.TestCase):
    def test_saved_draft_and_credentials_survive_server_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path=str(Path(directory)/'drafts.db')
            with patch.dict('os.environ', {'PL_DB_PATH':path}):
                with TestClient(create_app(config(console_demo_enabled=False))) as client:
                    store=client.app.state.pl.store
                    store.set_console_user('alex','Alex','carer')
                    store.link_console_user('alex','demo-margaret')
                    headers={'Authorization':'Bearer '+store.issue_console_token('alex')}
                    created=client.post('/api/console/words/margaret',headers=headers,
                        json={'text':'Can you open the window?','kind':'phrase'})
                    self.assertEqual(created.status_code,201)
                    word=created.json()['word']
                with TestClient(create_app(config(console_demo_enabled=False))) as client:
                    words=client.get('/api/console/words/margaret',headers=headers).json()['words']
                    self.assertIn(word,words)
                    self.assertEqual(word['status'],'draft')

    def test_judge_creation_only_writes_isolated_demo_store(self):
        with TestClient(create_app(config(console_demo_enabled=True))) as client:
            token=client.post('/api/console/demo/session').json()['token']
            response=client.post('/api/console/words/margaret',
                headers={'Authorization':'Bearer '+token},json={'text':'Demo phrase','kind':'phrase'})
            self.assertEqual(response.status_code,201)
            wid=response.json()['word']['id']
            self.assertIsNone(client.app.state.pl.store._read_word(wid))
            self.assertIsNotNone(client.app.state.pl.console_demo_store._read_word(wid))
