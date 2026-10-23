"""Fixed Magpie clips, synthesized once before the voice runtime accepts sessions."""
import wave
from .processing import RATE,normalize

# The caption remains 'mm'; Magpie gets a pronounceable nonverbal acknowledgment.
FIXED_LINES = {
    'mm':'Mm-hmm.', 'Want a hint?':'Want a hint?', 'Yes.':'Yes.',
    'Take your time.':'Take your time.', 'No rush.':'No rush.',
    'A bit stronger?':'A bit stronger?', "Let's try another.":"Let's try another.",
    'Want a rest?':'Want a rest?', 'Well done today.':'Well done today.',
    'Thanks.':'Thanks.',
}


def prepare_fixed(runtime):
    from ..app.nemo_stream import synthesize
    clips={}
    for key,text in FIXED_LINES.items():
        path=getattr(runtime.settings,'backchannel_clip_path','')
        if key=='mm' and path:
            with wave.open(path,'rb') as audio:
                if (audio.getnchannels()!=1 or audio.getsampwidth()!=2
                        or audio.getframerate()!=RATE or audio.getcomptype()!='NONE'
                        or not int(RATE*.1)<=audio.getnframes()<=RATE*3):
                    raise ValueError('Backchannel must be mono 22.05 kHz PCM16, 0.1 to 3 seconds')
                pcm=normalize(audio.readframes(audio.getnframes()),runtime.settings.clip_lufs)
        else:
            pcm=synthesize(runtime,text)
        if not pcm or len(pcm)%2 or len(pcm)>RATE*2*20:
            raise ValueError('Invalid fixed audio clip')
        clips[key]=pcm
    # Publish only a fully prepared set; no partial warm-up is reported as ready.
    runtime.fixed_clips=clips
    return len(clips)
