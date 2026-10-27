"""Offline deployment safeguards; no Docker daemon, network or live DB required."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs
try:
    import yaml
except ImportError:
    yaml=None
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('postgres_deploy',ROOT/'scripts/postgres_deploy.py')
deploy=importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


class PostgresDeploymentTests(unittest.TestCase):
    def setUp(self):
        cli=patch.object(deploy,'compose_command',return_value=['docker','compose'])
        cli.start()
        self.addCleanup(cli.stop)
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.config=self.root/'private'
        deploy.initialize(self.config,55432)

    def change(self,**changes):
        values=deploy.read_config(self.config)
        values.update(changes)
        (self.config/'.env').write_text(''.join(k+'='+json.dumps(v)+'\n' for k,v in values.items()))

    def test_private_init_is_unique_and_never_rotates_existing_secrets(self):
        values=deploy.read_config(self.config)
        secret_dir=Path(values['PL_PG_SECRET_DIR'])
        admin=(secret_dir/'admin_password').read_bytes()
        app=(secret_dir/'app_password').read_bytes()
        self.assertNotEqual(admin,app)
        self.assertGreater(len(app.strip()),32)
        with self.assertRaises(ValueError):deploy.initialize(self.config,55432)
        self.assertEqual((secret_dir/'app_password').read_bytes(),app)
        self.assertNotIn(app.decode().strip(),(self.config/'.env').read_text())
        if os.name!='nt':self.assertEqual(self.config.stat().st_mode & 0o777,0o700)

    def test_invalid_port_creates_nothing(self):
        target=self.root/'bad'
        with self.assertRaises(ValueError):deploy.initialize(target,0)
        self.assertFalse(target.exists())

    def test_default_compose_is_loopback_and_private_env_file(self):
        command=deploy.compose(self.config,False)
        self.assertEqual(command[:2],['docker','compose'])
        self.assertIn(str(self.config/'.env'),command)
        self.assertNotIn(str(self.config/'secrets/app_password'),command)
        self.assertEqual(deploy.read_config(self.config)['PL_PG_BIND'],'127.0.0.1')

    def test_remote_bind_requires_tls_and_existing_certificates(self):
        self.change(PL_PG_BIND='0.0.0.0')
        with self.assertRaises(ValueError):deploy.compose(self.config,False)
        with self.assertRaises(ValueError):deploy.compose(self.config,True)
        cert=self.root/'cert.pem';cert.write_text('test')
        key=self.root/'key.pem';key.write_text('test')
        self.change(PL_PG_TLS_CERT=str(cert),PL_PG_TLS_KEY=str(key))
        self.assertIn(str(ROOT/'deploy/postgres/compose.tls.yaml'),deploy.compose(self.config,True))

    def test_exported_bind_cannot_bypass_file_validation(self):
        with patch.dict(os.environ,{'PL_PG_BIND':'0.0.0.0'}):
            with self.assertRaises(ValueError):deploy.compose(self.config,False)

    def test_app_env_preserves_shared_keys_and_source_but_removes_sqlite_path(self):
        source=self.root/'source.env'
        original='SESSION_TOKEN_SECRET="synthetic-signing"\nVOICE_SERVICE_SECRET="synthetic-service"\nNEBIUS_API_KEY="synthetic-nebius"\nPL_DB_PATH="pl.db"\nDATABASE_URL="sqlite:///pl.db"\n'
        source.write_text(original)
        out=self.root/'pg.env'
        deploy.app_environment(self.config,source,out,'127.0.0.1',55432,'disable')
        values=dotenv_values(out,interpolate=False)
        self.assertEqual(source.read_text(),original)
        self.assertEqual(values['SESSION_TOKEN_SECRET'],'synthetic-signing')
        self.assertEqual(values['VOICE_SERVICE_SECRET'],'synthetic-service')
        self.assertEqual(values['NEBIUS_API_KEY'],'synthetic-nebius')
        self.assertNotIn('PL_DB_PATH',values)
        url=urlsplit(values['DATABASE_URL'])
        self.assertEqual(url.hostname,'127.0.0.1')
        self.assertEqual(url.port,55432)
        self.assertEqual(url.username,'patient_listener_app')
        self.assertEqual(url.path,'/patient_listener')
        with self.assertRaises(FileExistsError):
            deploy.app_environment(self.config,source,out,'127.0.0.1',55432,'disable')

    def test_remote_app_url_requires_tls_and_encodes_ca_path(self):
        with self.assertRaises(ValueError):
            deploy.app_environment(self.config,None,self.root/'bad.env','db.example.com',55432,'disable')
        ca=self.root/'CA with spaces.pem';ca.write_text('synthetic')
        out=self.root/'tls.env'
        deploy.app_environment(self.config,None,out,'db.example.com',55432,'verify-full',ca)
        url=urlsplit(dotenv_values(out)['DATABASE_URL'])
        self.assertEqual(parse_qs(url.query)['sslmode'],['verify-full'])
        self.assertEqual(parse_qs(url.query)['sslrootcert'],[ca.resolve().as_posix()])

    def test_secret_password_is_url_encoded(self):
        secret=self.config/'secrets/app_password'
        if os.name!='nt':secret.chmod(0o600)
        else:secret.chmod(0o666)
        secret.write_text('synthetic@password:/?#%')
        out=self.root/'encoded.env'
        deploy.app_environment(self.config,None,out,'127.0.0.1',55432,'disable')
        url=dotenv_values(out)['DATABASE_URL']
        self.assertIn('synthetic%40password%3A%2F%3F%23%25',url)
        self.assertEqual(urlsplit(url).hostname,'127.0.0.1')

    def test_cli_does_not_print_generated_secret_or_url(self):
        output=io.StringIO()
        with redirect_stdout(output):
            code=deploy.main(['--config-dir',str(self.config),'app-env','--out',str(self.root/'cli.env')])
        self.assertEqual(code,0)
        password=(self.config/'secrets/app_password').read_text().strip()
        self.assertNotIn(password,output.getvalue())
        self.assertNotIn('postgresql+asyncpg://',output.getvalue())

    def test_backup_is_binary_private_and_failure_never_publishes_dump(self):
        def dump(command,**kwargs):
            self.assertIn('pg_dump',command)
            kwargs['stdout'].write(b'PGDMPsynthetic')
            return SimpleNamespace(returncode=0)
        with patch.object(deploy.subprocess,'run',side_effect=dump):
            path=deploy.backup(['docker','compose'],self.config)
        self.assertEqual(path.read_bytes(),b'PGDMPsynthetic')
        if os.name!='nt':self.assertEqual(path.stat().st_mode & 0o777,0o600)
        with patch.object(deploy.subprocess,'run',return_value=SimpleNamespace(returncode=1)):
            with self.assertRaises(ValueError):deploy.backup(['docker','compose'],self.config)
        self.assertEqual(len(list((self.config/'backups').glob('*.dump'))),1)
        self.assertEqual(len(list((self.config/'backups').glob('*.partial'))),1)

    def test_restore_refuses_live_names_existing_target_and_invalid_dump(self):
        dump=self.root/'source.dump';dump.write_bytes(b'PGDMPsynthetic')
        with patch.object(deploy.subprocess,'run') as run:
            for name in ('patient_listener','postgres','pltest','patient_listener_restore;DROP DATABASE x'):
                with self.assertRaises(ValueError):deploy.restore(['docker'],dump,name)
            run.assert_not_called()
        with patch.object(deploy.subprocess,'run',return_value=SimpleNamespace(stdout='1\n')) as run:
            with self.assertRaises(ValueError):deploy.restore(['docker'],dump,'patient_listener_restore')
            self.assertEqual(run.call_count,1)
        dump.write_bytes(b'not-a-dump')
        with self.assertRaises(ValueError):deploy.restore(['docker'],dump,'patient_listener_restore')

    def test_restore_uses_only_new_isolated_database(self):
        dump=self.root/'source.dump';dump.write_bytes(b'PGDMPsynthetic')
        with patch.object(deploy.subprocess,'run',side_effect=[SimpleNamespace(stdout=''),
                          SimpleNamespace(returncode=0),SimpleNamespace(returncode=0)]) as run:
            deploy.restore(['docker'],dump,'patient_listener_restore_demo')
        calls=[call.args[0] for call in run.call_args_list]
        self.assertIn('createdb',calls[1])
        self.assertIn('--owner=patient_listener_app',calls[1])
        self.assertIn('--dbname=patient_listener_restore_demo',calls[2])
        self.assertNotIn('--dbname=patient_listener',calls[2])

    @unittest.skipUnless(yaml is not None, 'Optional PyYAML is needed for offline Compose parsing')
    def test_compose_has_persistence_file_secrets_and_native_tls_overlay(self):
        base=yaml.safe_load((ROOT/'deploy/postgres/compose.yaml').read_text())
        db=base['services']['postgres']
        self.assertEqual(db['environment']['POSTGRES_USER'],'listener_admin')
        self.assertIn('POSTGRES_PASSWORD_FILE',db['environment'])
        self.assertNotIn('POSTGRES_PASSWORD',db['environment'])
        self.assertTrue(any('pgdata:/var/lib/postgresql/data'==v for v in db['volumes']))
        tls=yaml.safe_load((ROOT/'deploy/postgres/compose.tls.yaml').read_text())
        self.assertIn('ssl=on',tls['services']['postgres']['command'])
        hba=(ROOT/'deploy/postgres/pg_hba.tls.conf').read_text()
        self.assertIn('hostnossl all all 0.0.0.0/0 reject',hba)
        self.assertIn('patient_listener_app',hba)
        initializer=(ROOT/'deploy/postgres/init-app-user.sh').read_text()
        self.assertIn('NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION',initializer)
        self.assertIn('\\getenv app_password',initializer)


class ComposeDetectionTests(unittest.TestCase):
    def test_plugin_is_preferred(self):
        with patch.object(deploy.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='2.40.0')) as run:
            self.assertEqual(deploy.compose_command(), ['docker', 'compose'])
            self.assertEqual(run.call_count, 1)

    def test_standalone_v5_is_supported(self):
        with patch.object(deploy.subprocess, 'run', side_effect=[SimpleNamespace(returncode=1, stdout=''), SimpleNamespace(returncode=0, stdout='5.0.2')]):
            self.assertEqual(deploy.compose_command(), ['docker-compose'])

    def test_legacy_v1_is_rejected(self):
        with patch.object(deploy.subprocess, 'run', side_effect=[FileNotFoundError(), SimpleNamespace(returncode=0, stdout='1.29.2')]):
            with self.assertRaises(ValueError): deploy.compose_command()

    def test_timeouts_and_missing_commands_are_reported(self):
        with patch.object(deploy.subprocess, 'run', side_effect=[deploy.subprocess.TimeoutExpired('docker', 10), FileNotFoundError()]):
            with self.assertRaises(ValueError): deploy.compose_command()
