"""Run a JavaScript orchestration file; no model-side individual MCP tool calls."""
import argparse
import asyncio
import json
import os
from pathlib import Path
from engine import Engine, load_config


async def main(args):
    config = load_config(args.backends)
    engine = Engine(config['catia-v5']['env']['PHYXI_NATIVE_WORKSPACE'], config, args.node)
    if args.action == 'status':
        result = engine.status(args.request_id)
    elif args.action == 'catalog':
        result = await engine.catalog(args.server, args.names)
    else:
        result = await engine.start(args.request_id, args.file.read_text(encoding='utf-8-sig'))
        if engine.tasks:
            await asyncio.gather(*engine.tasks)
            result = engine.status(args.request_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backends', type=Path, default=os.environ.get('PHYXI_PTC_BACKENDS'))
    parser.add_argument('--node', default=os.environ.get('PHYXI_PTC_NODE'))
    actions = parser.add_subparsers(dest='action', required=True)
    run = actions.add_parser('run')
    run.add_argument('--request-id', required=True)
    run.add_argument('--file', type=Path, required=True)
    status = actions.add_parser('status')
    status.add_argument('--request-id', required=True)
    catalog = actions.add_parser('catalog')
    catalog.add_argument('--server', choices=['catia-v5', 'native-modeling'], required=True)
    catalog.add_argument('--names', nargs='*', default=[])
    args = parser.parse_args()
    if not args.backends or not args.node:
        parser.error('Provide --backends and --node, or their PHYXI_PTC_* environment values')
    asyncio.run(main(args))
