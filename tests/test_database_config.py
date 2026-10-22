"""Environment precedence and portable query bindings; no database server needed."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from patient_listener.config import Settings
from patient_listener.store.factory import open_store


class ConfigTests(unittest.TestCase):
    def test_settings_read_current_environment_and_hide_secrets(self):
        with patch.dict(os.environ,{'NEBIUS_API_KEY':'private-key','DATABASE_URL':'postgresql://user:private-pass@host/db'}):
            settings=Settings()
            self.assertEqual(settings.nebius_api_key,'private-key')
            self.assertNotIn('private-key',repr(settings));self.assertNotIn('private-pass',repr(settings))

    def test_dotenv_preserves_injected_values_and_does_not_expand_secrets(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'.env'
            path.write_text('VOICE_ENABLED=true\nNEBIUS_API_KEY="literal${UNSET}-value"\n',encoding='utf-8')
            env={**os.environ,'PL_ENV_FILE':str(path),'VOICE_ENABLED':'false'}
            env.pop('NEBIUS_API_KEY',None)
            script="from patient_listener.config import Settings; s=Settings(); assert not s.voice_enabled; assert s.nebius_api_key=='literal${UNSET}-value'; print('ok')"
            result=subprocess.run([sys.executable,'-c',script],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout.strip(),'ok')

    def test_sqlite_explicit_selection_and_no_unknown_driver_fallback(self):
        store=open_store(Settings(database_url='sqlite:///:memory:',ai_enabled=False))
        self.addCleanup(store.close)
        self.assertFalse(store.is_ai_enabled())
        with self.assertRaises(ValueError):open_store(Settings(database_url='mysql://wrong'))
        with self.assertRaises(ValueError):
            open_store(Settings(database_url='postgresql://unused'),sqlite_path='pl.db')

    def test_production_requires_postgres(self):
        with self.assertRaisesRegex(ValueError,'PostgreSQL'):
            Settings(environment='production',database_url='sqlite:///:memory:',
                     require_https=True,session_token_secret='secret').assert_safe_startup()

    def test_parameter_binding_preserves_quoted_question_marks(self):
        from patient_listener.store.postgres_store import bind_sql
        sql,params=bind_sql("SELECT '?' as example, ? as value, 'it''s ?' as other",('private',))
        self.assertEqual(sql,"SELECT '?' as example, :p0 as value, 'it''s ?' as other")
        self.assertEqual(params,{'p0':'private'})
        with self.assertRaises(ValueError):bind_sql('SELECT ?',())

    def test_managed_postgres_tls_options(self):
        from patient_listener.store.postgres_store import postgres_engine_options
        url, args = postgres_engine_options('postgresql://user:pass@host/db?sslmode=verify-full')
        self.assertNotIn('sslmode', url.query)
        self.assertEqual(args['ssl'], 'verify-full')
        with self.assertRaises(ValueError):
            postgres_engine_options('postgresql://host/db?sslmode=invalid')
