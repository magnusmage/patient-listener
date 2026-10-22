"""Hermes registration contract and HTTP adapter tests; no Hermes install/model calls."""
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

ROOT=Path(__file__).resolve().parents[1]/'integrations'/'hermes'/'patient_listener'
SPEC=importlib.util.spec_from_file_location('pl_hermes_plugin_test',ROOT/'__init__.py',
                                           submodule_search_locations=[str(ROOT)])
plugin=importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name]=plugin
SPEC.loader.exec_module(plugin)
Client=plugin.Client
TOKEN='plagent_private-test-token'


class Context:
    def __init__(self): self.tools={};self.hooks={}
    def register_tool(self,**entry): self.tools[entry['name']]=entry
    def register_hook(self,name,handler): self.hooks[name]=handler


def response(data): return io.BytesIO(json.dumps(data).encode())


class HermesPluginTests(unittest.TestCase):
    def client(self):
        client=Client('http://127.0.0.1:8000',TOKEN)
        client._opener=Mock()
        return client

    def test_registers_only_two_tools_without_network_or_secrets_in_schema(self):
        ctx=Context()
        with patch.object(plugin.Client,'_request',side_effect=AssertionError('No network at registration')):
            plugin.register(ctx)
        self.assertEqual(set(ctx.tools),{'add_word_draft','progress_summary'})
        for name,entry in ctx.tools.items():
            self.assertEqual(entry['toolset'],'patient_listener')
            self.assertEqual(entry['schema']['name'],name)
            self.assertFalse(entry['schema']['parameters']['additionalProperties'])
            for secret in (TOKEN,'person_id','helper_id','base_url','api_key'):
                self.assertNotIn(secret,json.dumps(entry['schema']))
        self.assertEqual(ctx.hooks['pre_tool_call']('terminal')['action'],'block')
        self.assertIsNone(ctx.hooks['pre_tool_call']('add_word_draft'))

    def test_missing_credentials_disables_tools_without_leaking_exception(self):
        ctx=Context();plugin.register(ctx)
        with patch.dict('os.environ',{'PATIENT_LISTENER_AGENT_TOKEN':''}):
            self.assertFalse(ctx.tools['add_word_draft']['check_fn']())
            result=json.loads(ctx.tools['add_word_draft']['handler']({}))
            self.assertEqual(result['error'],'tool_unavailable')

    def test_http_draft_has_fixed_endpoint_and_credential_only_in_header(self):
        client=self.client()
        client._opener.open.return_value=response({'word_id':'w-'+'a'*32,'draft_created':True,
            'replayed':False,'console_path':'https://evil.example/steal'})
        result=client.add_word_draft({'request_id':'draft1','text':'Milo','kind':'person'})
        request=client._opener.open.call_args.args[0]
        self.assertEqual(request.full_url,'http://127.0.0.1:8000/api/agent/tools/add_word_draft')
        self.assertEqual(request.get_header('Authorization'),'Bearer '+TOKEN)
        self.assertEqual(request.get_header('Idempotency-key'),'draft1')
        self.assertNotIn(TOKEN,str(json.loads(request.data)))
        self.assertNotIn(TOKEN,str(result))
        self.assertEqual(result['console_url'],'http://127.0.0.1:8000/console.html')
        self.assertNotIn('evil',str(result))

    def test_bad_arguments_never_make_network_request(self):
        client=self.client()
        for params in ({'person_id':'another'}, {'request_id':'r','text':'x'*61,'kind':'person'},
                       {'request_id':'r','text':'Milo','kind':[]},
                       {'request_id':'r','text':'a\nb','kind':'person'},
                       {'request_id':'bad key','text':'Milo','kind':'person'}):
            self.assertEqual(client.add_word_draft(params)['error'],'invalid_arguments')
        self.assertEqual(client.progress_summary({'person':'another'})['error'],'invalid_arguments')
        client._opener.open.assert_not_called()

    def test_remote_plaintext_credentials_and_url_overrides_are_denied(self):
        for url in ('http://remote.example','https://user:pass@remote.example',
                    'https://remote.example/path','https://remote.example?token=bad',
                    'https://remote.example#fragment'):
            with self.assertRaises(ValueError): Client(url,TOKEN)
        self.assertIsInstance(Client('https://api.example',TOKEN),Client)

    def test_provider_or_http_error_details_never_reach_model(self):
        for exc in (HTTPError('url',401,'private secret',{},None),URLError('private secret')):
            client=self.client();client._opener.open.side_effect=exc
            result=client.progress_summary({})
            self.assertNotIn('private secret',str(result))
            self.assertNotIn(TOKEN,str(result))
        client=self.client();client._opener.open.return_value=response({'error':'private secret'})
        self.assertNotIn('private secret',str(client.progress_summary({})))

    def test_summary_is_exact_template_and_rejects_interpretations(self):
        client=self.client()
        fixed="This week: 4 words found without a hint, 2 after a hint. I can't say how her speech or health is; her SLT or doctor can."
        data={'summary':fixed,'found_without_hint':4,'found_with_hint':2,'period_days':7}
        client._opener.open.return_value=response(data)
        self.assertEqual(client.progress_summary({})['summary'],fixed)
        client._opener.open.return_value=response({**data,'summary':'Her speech is improving.'})
        self.assertEqual(client.progress_summary({})['error'],'invalid_response')
        client._opener.open.return_value=response({**data,'found_without_hint':True})
        self.assertEqual(client.progress_summary({})['error'],'invalid_response')

    def test_redirect_handler_never_forwards_credential(self):
        self.assertIsNone(plugin.client.NoRedirect().redirect_request(None,None,302,'',{},'https://evil.example'))


class PluginBackendIntegrationTests(unittest.TestCase):
    def test_registered_tools_reach_real_backend_and_preserve_draft_only_scope(self):
        from fastapi.testclient import TestClient
        from patient_listener.app.server import create_app
        from patient_listener.config import Settings
        from patient_listener.store.agent_store import AgentStore
        with TestClient(create_app(Settings(ai_enabled=False,voice_enabled=False,nebius_api_key=''))) as backend:
            store=backend.app.state.pl.store
            for uid,role in (('hermes','agent'),('sam','therapist')):
                store.set_console_user(uid,uid,role);store.link_console_user(uid,'demo-margaret')
            token=AgentStore(store).issue_token('hermes','sam','demo-margaret')
            def open_request(request,timeout):
                result=backend.request(request.method,request.full_url,content=request.data,
                                       headers=dict(request.header_items()))
                if result.status_code>=400:
                    raise HTTPError(request.full_url,result.status_code,'',{},io.BytesIO(result.content))
                return io.BytesIO(result.content)
            client=Client('http://127.0.0.1:8000',token)
            client._opener=SimpleNamespace(open=open_request)
            ctx=Context();plugin.register(ctx)
            with patch.object(plugin,'Client',return_value=client):
                add=ctx.tools['add_word_draft']['handler']
                params={'request_id':'hermes-test-1','text':'Milo','kind':'person'}
                first=json.loads(add(params));second=json.loads(add(params))
                self.assertEqual(first['word_id'],second['word_id'])
                self.assertTrue(second['replayed'])
                self.assertEqual(store._read_word(first['word_id']).status.value,'draft')
                summary=json.loads(ctx.tools['progress_summary']['handler']({}))
                self.assertEqual(summary['found_without_hint'],0)
                self.assertIn("I can't say",summary['summary'])
