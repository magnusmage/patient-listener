"""Standalone standard-library client for the two allowed backend tools.

No patient-listener package, GPU dependency or model SDK is imported into Hermes.
"""
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, base_url, token):
        parsed=urlsplit(base_url)
        if (parsed.scheme not in {'http','https'} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {'','/'}
                or any(ord(c)<32 or ord(c)==127 for c in base_url)):
            raise ValueError('Invalid configured API origin')
        if parsed.scheme == 'http' and parsed.hostname not in {'127.0.0.1','localhost','::1'}:
            raise ValueError('Remote agent API connections require HTTPS')
        if (not isinstance(token,str) or not token.startswith('plagent_') or len(token)>256
                or any(ord(c)<32 or ord(c)==127 for c in token)):
            raise ValueError('Invalid configured agent credential')
        if parsed.port is not None and not 1<=parsed.port<=65535:
            raise ValueError('Invalid configured API port')
        self._origin=base_url.rstrip('/')
        self._token=token
        self._opener=build_opener(NoRedirect)

    @staticmethod
    def _error(code):
        return {'error':code, 'message':'Tool did not complete. Check the configured service; '
                'retry a draft with the same request_id. Never claim it was approved.'}

    def _request(self, endpoint, body=None, request_id=None):
        # Endpoint and method are chosen by code, never by a model argument.
        if endpoint not in {'add_word_draft','progress_summary'}:
            return self._error('tool_not_allowed')
        headers={'Authorization':'Bearer '+self._token,'Content-Type':'application/json'}
        if request_id: headers['Idempotency-Key']=request_id
        request=Request(self._origin+'/api/agent/tools/'+endpoint,
            data=None if body is None else json.dumps(body).encode(),headers=headers,
            method='GET' if body is None else 'POST')
        try:
            with self._opener.open(request,timeout=8) as response:
                data=response.read(16385)
            if len(data)>16384: return self._error('invalid_response')
            result=json.loads(data)
            if not isinstance(result,dict) or 'error' in result:
                return self._error('invalid_response')
            return result
        except HTTPError as exc:
            return self._error('authentication_required' if exc.code in {401,403}
                               else 'request_conflict' if exc.code==409 else 'request_rejected')
        except (URLError,TimeoutError,OSError,ValueError):
            return self._error('service_unavailable')

    def add_word_draft(self, params):
        allowed={'request_id','text','kind','meaning_cue','first_sound'}
        if not isinstance(params,dict) or set(params)-allowed:
            return self._error('invalid_arguments')
        request_id=params.get('request_id','')
        if not isinstance(request_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',request_id):
            return self._error('invalid_arguments')
        body={k:params.get(k,'') for k in ('text','kind','meaning_cue','first_sound')}
        for key,maximum in (('text',60),('meaning_cue',90),('first_sound',4)):
            value=body[key]
            if not isinstance(value,str): return self._error('invalid_arguments')
            value=value.strip()
            if len(value)>maximum or any(ord(c)<32 or ord(c)==127 for c in value):
                return self._error('invalid_arguments')
            body[key]=value
        if not body['text'] or not isinstance(body['kind'],str) or body['kind'] not in {'person','place','food','object','activity','phrase'}:
            return self._error('invalid_arguments')
        result=self._request('add_word_draft',body,request_id)
        if 'error' in result: return result
        if (not isinstance(result.get('word_id'),str)
                or not re.fullmatch(r'w-[0-9a-f]{32}',result['word_id'])
                or result.get('draft_created') is not True or type(result.get('replayed')) is not bool):
            return self._error('invalid_response')
        return {'word_id':result['word_id'],'draft_created':True,'replayed':result['replayed'],
                'console_url':self._origin+'/console.html',
                'message':'Draft recorded. An authorised human must review it in the console.'}

    def progress_summary(self, params):
        if not isinstance(params,dict) or params:
            return self._error('invalid_arguments')
        result=self._request('progress_summary')
        if 'error' in result: return result
        without=result.get('found_without_hint'); with_hint=result.get('found_with_hint')
        if (type(without) is not int or type(with_hint) is not int
                or not 0<=without<=1000000 or not 0<=with_hint<=1000000 or result.get('period_days')!=7):
            return self._error('invalid_response')
        fixed=(f'This week: {without} words found without a hint, {with_hint} after a hint. '
               "I can't say how her speech or health is; her SLT or doctor can.")
        if result.get('summary') != fixed:
            return self._error('invalid_response')
        return {'summary':fixed,'found_without_hint':without,'found_with_hint':with_hint,'period_days':7}
