"""Hermes plugin: two fixed tools; no model calls or network requests at registration."""
import json
import os
from .client import Client
from .schemas import ADD_WORD_SCHEMA, SUMMARY_SCHEMA

ALLOWED = frozenset({'add_word_draft','progress_summary'})


def register(ctx):
    def client():
        return Client(os.environ.get('PATIENT_LISTENER_API_URL','http://127.0.0.1:8000'),
                      os.environ.get('PATIENT_LISTENER_AGENT_TOKEN',''))

    def available():
        try:
            client()
            return True
        except (ValueError,TypeError):
            return False

    def handler(method):
        def call(params, **kwargs):
            # Runtime keywords are not model arguments and are never logged/stored.
            # This single-binding adapter is for a private test profile. Telegram
            # requires verified routing before a multi-user gateway is enabled.
            try:
                return json.dumps(getattr(client(),method)(params))
            except Exception:
                # Hermes wraps unhandled exception messages; do not expose secrets there.
                return json.dumps({'error':'tool_unavailable','message':'Check the configured agent service.'})
        return call

    for schema in (ADD_WORD_SCHEMA,SUMMARY_SCHEMA):
        ctx.register_tool(name=schema['name'],toolset='patient_listener',schema=schema,
                          handler=handler(schema['name']),check_fn=available)

    def guard(tool_name, **kwargs):
        if tool_name not in ALLOWED:
            return {'action':'block','message':'This profile permits only draft creation and fixed progress counts.'}
    ctx.register_hook('pre_tool_call',guard)
