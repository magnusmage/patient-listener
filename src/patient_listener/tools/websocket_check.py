"""Workbook G-02 synthetic echo test. No models, patient data or cloud creation."""
import argparse
import asyncio
import getpass
import json
import math
import os
from pathlib import Path
import time
from urllib.parse import urlsplit


def validate_url(value):
    url = urlsplit(value)
    if url.username or url.password or url.query or url.fragment or not url.hostname:
        raise ValueError('Use an echo URL without credentials, query or fragment')
    if url.scheme != 'wss' and not (url.scheme == 'ws' and url.hostname in {'localhost','127.0.0.1','::1'}):
        raise ValueError('Use wss:// outside loopback')
    return value


def summary(samples, elapsed, seconds, location):
    ordered = sorted(samples)
    def percentile(p):
        return round(ordered[max(0, math.ceil(len(ordered)*p)-1)],3)
    full = seconds >= 600 and elapsed >= 600
    latency = max(ordered) < 200
    return {'location':location, 'samples':len(samples), 'connected_seconds':round(elapsed,3),
            'p50_ms':percentile(.5), 'p95_ms':percentile(.95), 'max_ms':round(max(ordered),3),
            'continuous_connection':True, 'latency_under_200ms':latency,
            'status':'full_duration' if full else 'quick_check_only',
            'g02_location_pass':full and latency and location in {'Pakistan','UK'}}


async def measure(url, token, seconds, location):
    from websockets.asyncio.client import connect
    class NoRedirect(connect):
        def process_redirect(self, exc):
            return exc  # Do not forward the disposable bearer credential anywhere else.
    samples = []
    async with NoRedirect(url, additional_headers={'Authorization':'Bearer '+token},
                          open_timeout=10, close_timeout=5, max_size=64, compression=None,
                          ping_interval=20, ping_timeout=20) as ws:
        started = time.monotonic()
        while time.monotonic()-started < seconds:
            payload = os.urandom(16)
            before = time.monotonic()
            await ws.send(payload)
            echoed = await asyncio.wait_for(ws.recv(),timeout=5)
            if echoed != payload:
                raise ValueError('Synthetic echo mismatch')
            samples.append((time.monotonic()-before)*1000)
            remaining = seconds-(time.monotonic()-started)
            if remaining > 0:
                await asyncio.sleep(min(1,remaining))
        return summary(samples,time.monotonic()-started,seconds,location)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True)
    parser.add_argument('--location',required=True,choices=['Pakistan','UK','local'])
    parser.add_argument('--seconds',type=int,default=600)
    parser.add_argument('--out',required=True,help='New report path; never overwritten')
    args = parser.parse_args(argv)
    try: validate_url(args.url)
    except ValueError as exc: parser.error(str(exc))
    if not 1 <= args.seconds <= 3600: parser.error('--seconds must be 1..3600')
    if Path(args.out).exists(): parser.error('--out must be a new report file')
    token = getpass.getpass('Disposable echo probe token (NOT a cloud/API key): ').strip()
    if not 32 <= len(token) <= 256 or any(ord(c)<33 or ord(c)>126 for c in token):
        parser.error('Use a disposable token of 32..256 printable ASCII characters')
    try:
        result = asyncio.run(measure(args.url,token,args.seconds,args.location))
    except Exception as exc:
        result = {'location':args.location,'status':'failed','error_type':type(exc).__name__,
                  'g02_location_pass':False}
    with Path(args.out).open('x',encoding='utf-8') as output:
        json.dump(result,output,indent=2)
    print(json.dumps(result,indent=2))
    if result['status']=='failed': return 1
    return 0 if result['latency_under_200ms'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
