"""Create one private local split-service config and launch either role from it."""
import argparse
import json
import os
from pathlib import Path
import secrets


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    init=sub.add_parser('init',help='Create a new private development config; does not change the database')
    init.add_argument('--db',default='pl.db')
    init.add_argument('--out',default='.env.split')
    init.add_argument('--api-port',type=int,default=8000)
    init.add_argument('--voice-port',type=int,default=8001)
    for command in ('check','run'):
        item=sub.add_parser(command)
        item.add_argument('role',choices=['api','voice'])
        item.add_argument('--env-file',default='.env.split')
    args=parser.parse_args(argv)
    if args.action=='init':
        path=Path(args.db).resolve()
        if not path.is_file():parser.error('--db must name the existing SQLite database used by your server')
        if not (1<=args.api_port<=65535 and 1<=args.voice_port<=65535) or args.api_port==args.voice_port:
            parser.error('Use two distinct ports between 1 and 65535')
        values={'PL_ENV':'development','DATABASE_URL':'sqlite:///'+path.as_posix(),'PL_DB_PATH':str(path),
                'SESSION_TOKEN_SECRET':secrets.token_urlsafe(48),'VOICE_SERVICE_SECRET':secrets.token_urlsafe(48),
                'VOICE_PUBLIC_WS_URL':f'ws://127.0.0.1:{args.voice_port}/ws',
                'VOICE_INTERNAL_URL':f'http://127.0.0.1:{args.voice_port}',
                'VOICE_ALLOWED_ORIGINS':f'http://127.0.0.1:{args.api_port},http://localhost:{args.api_port}',
                'PL_API_PORT':str(args.api_port),'PL_VOICE_PORT':str(args.voice_port),
                'PATIENT_ENROLLMENT_REQUIRED':'true','AI_ENABLED':'false','NEBIUS_API_KEY':'',
                'NIGHTLY_ENABLED':'false','REQUIRE_HTTPS':'false','TRUST_PROXY_HEADERS':'false',
                'ASR_MODEL':'nvidia/nemotron-speech-streaming-en-0.6b',
                'TTS_MODEL':'nvidia/magpie_tts_multilingual_357m','TTS_VOICE':'Aria',
                'HINT_AUDIO_RATE':'0.8','CLIP_LUFS':'-20.0','BOOST_ALPHA':'2.0'}
        try:
            fd=os.open(args.out,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as output:
                output.write('# PRIVATE: shared local setup; never commit, upload or paste this file.\n')
                for name,value in values.items():output.write(name+'='+json.dumps(value)+'\n')
        except FileExistsError:parser.error('The config already exists; reuse it instead of rotating shared secrets')
        print('Created private local config:',args.out)
        print('No database records were changed. Keep this same file for both services.')
        return 0
    env=Path(args.env_file).resolve()
    if not env.is_file():parser.error('Create the shared config first with services init')
    from dotenv import dotenv_values
    values=dotenv_values(env,interpolate=False)
    for name,value in values.items():
        if value is not None and name in os.environ and os.environ[name]!=value:
            parser.error('Exported '+name+' differs from the shared file. Unset it in this terminal and retry; no values were printed.')
    os.environ['PL_ENV_FILE']=str(env)
    from ..config import Settings, load_environment
    load_environment()
    # The role is explicit. Existing exported values still take precedence for data/secrets.
    os.environ['PL_SERVICE_ROLE']=args.role
    os.environ['VOICE_ENABLED']='true' if args.role=='voice' else 'false'
    os.environ['NIGHTLY_ENABLED']='false'
    os.environ['PL_PORT']=os.environ.get('PL_API_PORT' if args.role=='api' else 'PL_VOICE_PORT','8000' if args.role=='api' else '8001')
    if not os.environ['PL_PORT'].isdigit() or not 1<=int(os.environ['PL_PORT'])<=65535:
        parser.error('Configured port must be 1..65535')
    os.environ.setdefault('PL_HOST','127.0.0.1')
    cfg=Settings();cfg.assert_safe_startup()
    if args.action=='check':
        print('Configuration valid for role:',args.role)
        print('Port:',os.environ['PL_PORT'])
        print('Patient enrollment required:',cfg.requires_patient_enrollment)
        print('No database connection, model loading or paid call was performed.')
        return 0
    from ..app.__main__ import main as serve
    serve()
    return 0


if __name__=='__main__':
    raise SystemExit(main())
