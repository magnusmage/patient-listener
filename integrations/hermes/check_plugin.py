"""No-model registration check; --probe explicitly reads the configured backend summary."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe',action='store_true')
    args=parser.parse_args()
    root=Path(__file__).resolve().parent/'patient_listener'
    spec=importlib.util.spec_from_file_location('patient_listener_hermes_check',root/'__init__.py',
                                                submodule_search_locations=[str(root)])
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    class Context:
        def __init__(self):self.tools={};self.hooks={}
        def register_tool(self,**entry):self.tools[entry['name']]=entry
        def register_hook(self,name,handler):self.hooks[name]=handler
    ctx=Context();module.register(ctx)
    expected={'add_word_draft','progress_summary'}
    if set(ctx.tools)!=expected or ctx.hooks['pre_tool_call']('terminal').get('action')!='block':
        print('Plugin contract check failed');return 1
    print('Plugin registration contract passed: '+', '.join(sorted(ctx.tools)))
    print('No Hermes runtime or model was started.')
    if args.probe:
        try:
            client=module.Client(os.environ.get('PATIENT_LISTENER_API_URL','http://127.0.0.1:8000'),
                                 os.environ.get('PATIENT_LISTENER_AGENT_TOKEN',''))
            result=client.progress_summary({})
        except (ValueError,TypeError):
            print('Backend probe failed: check configured API origin and agent credential');return 1
        if 'error' in result:
            print('Backend probe failed: '+result['error']);return 1
        print('Backend summary tool verified; no model call was made.')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
