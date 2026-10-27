"""Private PostgreSQL setup and non-destructive administration for local/server Docker."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / 'deploy' / 'postgres' / 'private'


def write_new(path: Path, content: str, mode=0o600):
    fd=os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as file:
        file.write(content)
    if os.name != 'nt': path.chmod(mode)


def read_config(directory: Path) -> dict:
    path=directory / '.env'
    if not path.is_file(): raise ValueError('Run init first; existing configuration is required.')
    values={}
    for line in path.read_text(encoding='utf-8').splitlines():
        line=line.strip()
        if not line or line.startswith('#'):continue
        key,separator,value=line.partition('=')
        if not separator:raise ValueError('Invalid compose configuration line.')
        values[key.strip()]=json.loads(value) if value.startswith('"') else value.strip()
    return values


def initialize(directory: Path, port: int):
    if not 1 <= port <= 65535: raise ValueError('Port must be 1..65535.')
    if (directory / '.env').exists():raise ValueError('Configuration already exists; do not rotate secrets with init.')
    directory.mkdir(parents=True,exist_ok=True)
    if os.name != 'nt':directory.chmod(0o700)
    secret_dir=directory / 'secrets'
    secret_dir.mkdir(exist_ok=True)
    if os.name != 'nt':secret_dir.chmod(0o700)
    # Docker bind-mounted secrets must be readable by the container postgres UID.
    # Host traversal is restricted by the enclosing 0700 directories.
    for name in ('admin_password','app_password'):
        write_new(secret_dir/name,secrets.token_urlsafe(36)+'\n',0o444)
    values={'PL_PG_IMAGE':'postgres:16-bookworm','PL_PG_BIND':'127.0.0.1',
            'PL_PG_PORT':str(port),'PL_PG_SECRET_DIR':secret_dir.resolve().as_posix()}
    write_new(directory/'.env',''.join(k+'='+json.dumps(v)+'\n' for k,v in values.items()))


def compose_command() -> list[str]:
    """Find a modern Compose CLI without contacting the Docker daemon."""
    for command in (['docker', 'compose'], ['docker-compose']):
        try:
            result = subprocess.run(command + ['version', '--short'],
                                    capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            continue
        version = re.match(r'v?(\d+)\.', result.stdout.strip())
        if result.returncode == 0 and version and int(version.group(1)) >= 2:
            return command
    raise ValueError('Modern Docker Compose (v2 or newer) is required; neither command is available.')


def compose(directory: Path, tls: bool) -> list[str]:
    values=read_config(directory)
    for key,value in values.items():
        if key in os.environ and os.environ[key] != value:
            raise ValueError('Exported '+key+' conflicts with the private config; unset it and retry.')
    bind=values.get('PL_PG_BIND','127.0.0.1')
    try:local=ipaddress.ip_address(bind).is_loopback
    except ValueError:raise ValueError('PL_PG_BIND must be an IP address.') from None
    if not local and not tls:raise ValueError('Remote binding requires --tls and a firewall/VPN access policy.')
    if tls:
        for key in ('PL_PG_TLS_CERT','PL_PG_TLS_KEY'):
            if not Path(values.get(key,'')).is_file():raise ValueError('Configure existing TLS certificate and key files first.')
    result=compose_command()+['--project-name','patient-listener-db','--env-file',str(directory/'.env'),
            '-f',str(ROOT/'deploy/postgres/compose.yaml')]
    if tls:result+=['-f',str(ROOT/'deploy/postgres/compose.tls.yaml')]
    return result


def app_environment(directory, source, output, host, port, sslmode, ca_file=None, database='patient_listener'):
    from dotenv import dotenv_values
    if (not host or any(c.isspace() for c in host) or any(c in host for c in '/?#@')
            or not re.fullmatch(r'[A-Za-z0-9_.:\-]+',host)):
        raise ValueError('Use a database hostname/IP, not a URL.')
    try:local=ipaddress.ip_address(host).is_loopback
    except ValueError:local=host=='localhost'
    if sslmode=='disable' and not local:raise ValueError('Remote database connections require verify-full TLS.')
    if not 1 <= port <= 65535:raise ValueError('Port must be 1..65535.')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',database):raise ValueError('Invalid database name.')
    values={}
    if source is not None:
        if not source.is_file():raise ValueError('Source environment file does not exist.')
        values={k:v for k,v in dotenv_values(source,interpolate=False).items() if v is not None}
    password=(Path(read_config(directory)['PL_PG_SECRET_DIR'])/'app_password').read_text().strip()
    address='['+host+']' if ':' in host else host
    url=f'postgresql+asyncpg://patient_listener_app:{quote(password,safe="")}@{address}:{port}/{database}?sslmode={sslmode}'
    if ca_file:
        if sslmode!='verify-full' or not ca_file.is_file():raise ValueError('An existing CA file requires verify-full TLS.')
        url+='&sslrootcert='+quote(ca_file.resolve().as_posix(),safe='')
    values.pop('PL_DB_PATH',None)
    values.pop('PL_ENV_FILE',None)
    values['DATABASE_URL']=url
    write_new(output,''.join(k+'='+json.dumps(v)+'\n' for k,v in values.items()))


def backup(command, directory):
    folder=directory/'backups'
    folder.mkdir(exist_ok=True)
    if os.name!='nt':folder.chmod(0o700)
    name='patient-listener-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+secrets.token_hex(3)+'.dump'
    output=folder/name
    partial=folder/(name+'.partial')
    fd=os.open(partial,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as file:
        result=subprocess.run(command+['exec','-T','postgres','pg_dump','--username=listener_admin',
            '--dbname=patient_listener','--format=custom','--no-owner','--no-privileges'],stdout=file,stderr=subprocess.PIPE)
    if result.returncode:raise ValueError('Backup failed; incomplete .partial file retained privately.')
    if output.exists():raise ValueError('Refusing to overwrite a backup.')
    partial.rename(output)
    return output


def restore(command, source, database):
    if not re.fullmatch(r'patient_listener_restore(?:_[a-z0-9]+)?',database):
        raise ValueError('Restore is limited to a NEW patient_listener_restore or patient_listener_restore_SUFFIX database.')
    if not source.is_file():raise ValueError('Backup file not found.')
    with source.open('rb') as file:
        if file.read(5)!=b'PGDMP':raise ValueError('Use a PostgreSQL custom-format dump.')
    query="SELECT 1 FROM pg_database WHERE datname='"+database+"'"
    result=subprocess.run(command+['exec','-T','postgres','psql','--no-psqlrc','--username=listener_admin',
        '--dbname=postgres','--tuples-only','--no-align','--command',query],capture_output=True,text=True,check=True)
    if result.stdout.strip():raise ValueError('Restore target already exists; nothing overwritten.')
    subprocess.run(command+['exec','-T','postgres','createdb','--username=listener_admin',
        '--owner=patient_listener_app','--template=template0',database],check=True)
    with source.open('rb') as file:
        result=subprocess.run(command+['exec','-T','postgres','pg_restore','--username=listener_admin',
            '--role=patient_listener_app','--dbname='+database,'--exit-on-error','--clean','--if-exists',
            '--no-owner','--no-privileges'],stdin=file,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    if result.returncode:raise ValueError('Restore failed; isolated target retained for inspection. Live database unchanged.')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config-dir',type=Path,default=DEFAULT_CONFIG)
    parser.add_argument('--tls',action='store_true',help='Use the native PostgreSQL TLS overlay')
    sub=parser.add_subparsers(dest='action',required=True)
    init=sub.add_parser('init');init.add_argument('--port',type=int,default=55432)
    for action in ('check','up','status','stop','backup'):sub.add_parser(action)
    restore_parser=sub.add_parser('restore-test')
    restore_parser.add_argument('--source',type=Path,required=True)
    restore_parser.add_argument('--database',required=True)
    env=sub.add_parser('app-env')
    env.add_argument('--source-env',type=Path)
    env.add_argument('--out',type=Path,required=True)
    env.add_argument('--host',default='127.0.0.1')
    env.add_argument('--port',type=int,default=55432)
    env.add_argument('--database',default='patient_listener')
    env.add_argument('--sslmode',choices=('disable','verify-full'),default='disable')
    env.add_argument('--ca-file',type=Path)
    args=parser.parse_args(argv)
    directory=args.config_dir.resolve()
    try:
        if args.action=='init':
            initialize(directory,args.port)
            print('Private database configuration created. No database started or existing data changed.')
        elif args.action=='app-env':
            app_environment(directory,args.source_env,args.out,args.host,args.port,args.sslmode,args.ca_file,args.database)
            print('Private PostgreSQL application environment created. No secrets printed; source file unchanged.')
        else:
            command=compose(directory,args.tls)
            if args.action=='check':subprocess.run(command+['config','--quiet'],check=True)
            elif args.action=='up':subprocess.run(command+['up','-d','--wait'],check=True)
            elif args.action=='status':subprocess.run(command+['ps'],check=True)
            elif args.action=='stop':subprocess.run(command+['stop'],check=True)
            elif args.action=='backup':print('Backup completed:',backup(command,directory))
            elif args.action=='restore-test':
                restore(command,args.source,args.database)
                print('Restored into isolated database:',args.database)
    except (ValueError,FileExistsError,FileNotFoundError) as exc:
        # All generated validation messages are fixed; never emit a connection URL.
        print('Operation failed:',str(exc) if isinstance(exc,ValueError) else type(exc).__name__)
        return 1
    except subprocess.CalledProcessError:
        print('Docker database operation failed. Check service health; no credentials printed by this tool.')
        return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
