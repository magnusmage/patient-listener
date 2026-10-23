"""Prepared mono PCM16 audio. Optional audio libraries are imported only at use."""
from __future__ import annotations
import json
import math

RATE = 22050
GAP_MS = 500
VERSION = 'pl-audio-1'


def hint_profile(settings):
    return json.dumps({'version':VERSION, 'rate':getattr(settings,'hint_audio_rate',.8),
        'gap_ms':GAP_MS, 'lufs':getattr(settings,'clip_lufs',-20.0)},sort_keys=True)


def decode(pcm):
    import numpy as np
    if not isinstance(pcm,bytes) or not pcm or len(pcm)%2:
        raise ValueError('Expected nonempty mono PCM16')
    if len(pcm)>RATE*2*25:
        raise ValueError('Audio clip exceeds its duration budget')
    return np.frombuffer(pcm,dtype='<i2').astype('float64')/32768


def normalize(pcm,target=-20.0):
    """BS.1770 loudness with peak headroom; short clips repeat for measurement only."""
    import numpy as np
    import pyloudnorm as pyln
    audio=decode(pcm)
    if not math.isfinite(target) or not -30<=target<=-14:
        raise ValueError('Invalid loudness target')
    if not np.any(audio):
        raise ValueError('Speech synthesis returned silence')
    measured=audio if len(audio)>=int(RATE*.4) else np.tile(audio,math.ceil(RATE*.4/len(audio)))
    loudness=pyln.Meter(RATE).integrated_loudness(measured)
    if not math.isfinite(loudness):
        raise ValueError('Audio loudness could not be measured')
    gain=min(10**((target-loudness)/20),.98/float(np.max(np.abs(audio))))
    return np.rint(audio*gain*32767).astype('<i2').tobytes()


def stretch(pcm,speed=.8):
    import numpy as np
    from audiotsm import wsola
    from audiotsm.io.array import ArrayReader,ArrayWriter
    if speed not in (.8,1.0):
        raise ValueError('Hint speed must be 0.8 or the documented 1.0 fallback')
    if speed==1.0:return pcm
    audio=decode(pcm).astype('float32')
    # Pad WSOLA windows so its analysis does not discard the start/end of short words.
    pad=2048
    padded=np.pad(audio,(pad,pad))
    writer=ArrayWriter(1)
    wsola(1,speed=speed).run(ArrayReader(padded.reshape(1,-1)),writer)
    start=round(pad/speed)
    length=round(len(audio)/speed)
    output=writer.data[0,start:start+length]
    if len(output)<length:output=np.pad(output,(0,length-len(output)))
    if not np.any(output):raise ValueError('Time stretching produced silent audio')
    return np.rint(output.clip(-1,1)*32767).astype('<i2').tobytes()


def prepare_hint(parts,settings):
    """Slow each sentence without shifting pitch and separate sentences by 500 ms."""
    speed=getattr(settings,'hint_audio_rate',.8)
    clips=[stretch(part,speed) for part in parts]
    if not clips:raise ValueError('Hint has no sentences')
    gap=b'\0'*(RATE*2*GAP_MS//1000)
    return normalize(gap.join(clips),getattr(settings,'clip_lufs',-20.0))
