"""Authenticated, bounded CPU-to-GPU hint rendering. No retries or redirected secrets."""
import hashlib
import json
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler
from ..tools.generate_plan import NoRedirect
from ..voice.processing import hint_profile

MAX_PCM=22050*2*20


def contract(settings):
    data={'model':settings.tts_model,'voice':settings.tts_voice,'profile':hint_profile(settings),
          'sample_rate':22050,'channels':1,'format':'s16le'}
    return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()


class RemoteRenderError(RuntimeError):
    def __init__(self, busy=False):
        super().__init__('Remote voice renderer unavailable or incompatible')
        self.busy=busy


class RemoteRenderer:
    def __init__(self, settings, registry, person_id):
        self.settings,self.registry,self.person_id=settings,registry,person_id

    def _fetch(self, text):
        expected=contract(self.settings)
        payload={'person_id':self.person_id,'lease_owner':self.registry.owner(self.person_id),
                 'text':text,'contract':expected}
        request=Request(self.settings.voice_internal_url.rstrip('/')+'/internal/render',
            data=json.dumps(payload).encode(),method='POST',headers={
                'Content-Type':'application/json','X-PL-Service-Key':self.settings.voice_service_secret})
        try:
            with build_opener(ProxyHandler({}),NoRedirect).open(request,timeout=30) as response:
                if (response.headers.get('Content-Type')!='application/octet-stream'
                        or response.headers.get('X-PL-Audio-Contract')!=expected):
                    raise RemoteRenderError()
                pcm=response.read(MAX_PCM+1)
                if not pcm or len(pcm)%2 or len(pcm)>MAX_PCM:raise RemoteRenderError()
                return pcm
        except HTTPError as exc:
            raise RemoteRenderError(busy=exc.code==409) from None
        except Exception:
            raise RemoteRenderError() from None

    async def render(self, text):
        from .voice_connection import worker_call
        await self.registry.check_owned(self.person_id)
        result=await worker_call(self._fetch,text)
        await self.registry.check_owned(self.person_id)
        return result
