"""Build a local Codex marketplace, optionally binding existing MCP launch paths.

Default package is skill-only and pairs with migrate_mcp.py. --bundle-mcp is an
alternative to global registration, never an additional duplicate registration.
Generated absolute-path MCP configuration is machine-local, not portable.
"""
import argparse
import json
from pathlib import Path
import shutil

from migrate_mcp import read_selected


def build(destination, source=None, standalone=False):
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError('Refusing to replace existing extension: ' + str(destination))
    root = Path(__file__).resolve().parent
    if standalone:
        if source:
            raise ValueError('Standalone skill uses global MCP configuration')
        shutil.copytree(root / 'plugins/phyxi-catia/skills/catia-native', destination)
        return {'kind': 'standalone-skill', 'path': str(destination)}
    selected = read_selected(source) if source else None
    shutil.copytree(root / '.agents', destination / '.agents')
    shutil.copytree(root / 'plugins', destination / 'plugins')
    if selected:
        plugin = destination / 'plugins/phyxi-catia'
        (plugin / '.mcp.json').write_text(json.dumps({'mcpServers': selected}, indent=2), encoding='utf-8')
        manifest_path = plugin / '.codex-plugin/plugin.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest['mcpServers'] = './.mcp.json'
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return {'kind': 'plugin-with-mcp' if selected else 'skill-only-plugin', 'path': str(destination)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--bundle-mcp', type=Path, help='Existing local MCP JSON; alternative to global registration')
    parser.add_argument('--standalone-skill', action='store_true')
    args = parser.parse_args()
    print(json.dumps(build(args.out, args.bundle_mcp, args.standalone_skill), indent=2))
