"""Optional upstream extension, with original tool names/STA routing retained."""
import asyncio
import hashlib
import os
from pathlib import Path
import sys
import uuid
from plan_engine import PlanEngine, PlanInputError, PLAN_TOOLS

ADAPTER_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def make_server(upstream=None, workspace=None, gate=None):
    if upstream: sys.path.insert(0, str(Path(upstream).resolve()))
    from catia_mcp.server import CATIAMCPServer, structured_result, failure
    from jsonschema import validate, ValidationError
    from mcp.types import ImageContent, EmbeddedResource
    workspace = Path(workspace or os.environ['PHYXI_NATIVE_WORKSPACE']).resolve()
    gate = gate or os.environ['PHYXI_NATIVE_GATE']

    class PlanModule:
        def get_tool_definitions(self): return PLAN_TOOLS

    class EnhancedServer(CATIAMCPServer):
        def __init__(self):
            super().__init__()
            self.original_schemas = dict(self._schemas)
            self._tool_modules.append(PlanModule())
            self.plans = PlanEngine(workspace, gate, self.raw_dispatch, self.validate_original)

        def raw_dispatch(self, name, args):
            args = dict(args)
            if name in ('catia_save_document','catia_open_document') and args.get('file_path'):
                # CATIA SaveAs on this V5 rejects Windows paths with / separators.
                args['file_path'] = os.path.normpath(args['file_path'])
            return super()._execute_tool(name, args)

        def validate_original(self, name, args):
            if name not in self.original_schemas: raise ValueError('Unknown original CATIA tool: ' + name)
            validate(args, self.original_schemas[name])

        def catalog(self, names=(), include_schema=False):
            definitions = [d for m in self._tool_modules for d in m.get_tool_definitions()]
            if names: definitions = [d for d in definitions if d['name'] in names]
            tools = definitions if include_schema else [{'name':d['name'],'description':d['description']} for d in definitions]
            return {'ok': True, 'tools': tools, 'schemas_included': include_schema,
                    'dispatch': 'serial-STA', 'atomic_plan_mutex': True, 'automatic_retry_allowed': False,
                    'adapter': {'version': '0.7.0', 'pid': os.getpid(),
                                'source_sha256': ADAPTER_SOURCE_SHA256}}

        async def call_tool(self, name, arguments):
            # Progress/catalog is not queued behind long COM work on the STA.
            if name == 'catia_plan_status':
                try: validate(arguments, PLAN_TOOLS[1]['inputSchema'])
                except ValidationError as error: return failure('INVALID_ARGUMENT', error.message, 'validate', False, name)
                status = await asyncio.to_thread(self.plans.status, arguments.get('request_id'))
                if not arguments.get('request_id'):
                    status['plans'] = [{k:r.get(k) for k in ('request_id','status','completion','updated_at','declared_checks_passed','skipped_steps')}
                                       | {'last_event':r.get('events',[])[-1:] } for r in status['plans']]
                return structured_result({'ok': True, **status})
            if name == 'catia_plan_catalog':
                try: validate(arguments, PLAN_TOOLS[2]['inputSchema'])
                except ValidationError as error: return failure('INVALID_ARGUMENT', error.message, 'validate', False, name)
                return structured_result(self.catalog(arguments.get('names', ()), arguments.get('include_schema', False)))
            return await super().call_tool(name, arguments)

        def _execute_tool(self, name, arguments):
            try:
                if name == 'catia_plan_run':
                    validate(arguments, PLAN_TOOLS[0]['inputSchema'])
                    record = self.plans.run(arguments['request_id'], arguments['steps'])
                else:
                    record = self.plans.run('single-' + uuid.uuid4().hex, [{'id': 'single', 'tool': name, 'arguments': arguments}])
                result = structured_result({'ok': record['status'] == 'SUCCEEDED', 'code': record['status'],
                                            'tool': name, 'plan': record, 'effects': {'modified': None}})
                # Preserve native MCP images rather than hiding them in JSON text.
                for step in record['results']:
                    for content in step['raw'].get('content', []):
                        if content.get('type') == 'image': result.content.append(ImageContent(**content))
                        elif content.get('type') == 'resource': result.content.append(EmbeddedResource(**content))
                return result
            except (PlanInputError, ValidationError) as error:
                return failure('INVALID_PLAN', str(error), 'validate', False, name)

    return EnhancedServer()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--upstream', default=os.environ.get('CATIA_UPSTREAM'))
    args = parser.parse_args()
    workspace = Path(os.environ['PHYXI_NATIVE_WORKSPACE']).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault('CATIA_MCP_LOG_FILE', str(workspace / 'catia-mcp.log'))
    output = workspace / 'catia-v5-models'; output.mkdir(exist_ok=True)
    os.chdir(output)
    asyncio.run(make_server(args.upstream).run())


if __name__ == '__main__': main()
