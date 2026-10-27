"""Regression: shared SQLite must not mix/drop identities under concurrent reads."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from patient_listener.app.server import create_app
from patient_listener.config import Settings
from patient_listener.store.sqlite_store import SqliteStore


class ParallelConsoleAuthTests(unittest.TestCase):
    def test_shared_sqlite_disables_statement_cache(self):
        import sqlite3
        connect=sqlite3.connect
        with patch('patient_listener.store.sqlite_store.sqlite3.connect',wraps=connect) as factory:
            store=SqliteStore(check_same_thread=False,ai_enabled=False)
            try:
                self.assertEqual(factory.call_args.kwargs['cached_statements'],0)
            finally:store.close()

    def test_concurrent_tokens_keep_exact_identity_and_role(self):
        store=SqliteStore(check_same_thread=False,ai_enabled=False)
        self.addCleanup(store.close)
        cases=[]
        for name,role in [('sam','therapist'),('alex','carer'),('agent','agent')]:
            store.set_console_user(name,name,role)
            token=store.issue_console_token(name)
            cases.append((token,{'id':name,'display_name':name,'role':role}))
        cases.append(('not-a-token',None))
        barrier=threading.Barrier(12)
        def check(worker):
            barrier.wait(timeout=10)
            errors=Counter()
            for i in range(300):
                token,expected=cases[(worker+i)%len(cases)]
                try:
                    if store.console_user_for_token(token)!=expected:
                        errors['wrong_or_missing_identity']+=1
                except Exception as exc:errors[type(exc).__name__]+=1
            return errors
        with ThreadPoolExecutor(max_workers=12) as pool:
            errors=sum(pool.map(check,range(12)),Counter())
        self.assertEqual(dict(errors),{})

    def test_parallel_console_data_loads_accept_linked_therapist_and_reject_agent(self):
        cfg=Settings(ai_enabled=False,nebius_api_key='',voice_enabled=False,console_demo_enabled=False)
        with TestClient(create_app(cfg)) as client:
            store=client.app.state.pl.store
            for name,role in [('sam','therapist'),('agent','agent')]:
                store.set_console_user(name,name,role)
                for pid in ('demo-margaret','demo-joseph'):store.link_console_user(name,pid)
            sam={'Authorization':'Bearer '+store.issue_console_token('sam')}
            agent={'Authorization':'Bearer '+store.issue_console_token('agent')}
            paths=['me','caseload']+[
                section+'/'+person for person in ('margaret','joseph')
                for section in ('words','grid','settings','consent')]
            work=[('sam',path) for _ in range(8) for path in paths]
            work += [('agent','me') for _ in range(20)]
            def request(item):
                who,path=item
                response=client.get('/api/console/'+path,headers=sam if who=='sam' else agent)
                expected=200 if who=='sam' else 403
                return (who,path,response.status_code) if response.status_code!=expected else None
            with ThreadPoolExecutor(max_workers=12) as pool:
                failures=[x for x in pool.map(request,work) if x is not None]
            self.assertEqual(failures,[])
            self.assertEqual(client.get('/api/console/me',headers=sam).json()['id'],'sam')
