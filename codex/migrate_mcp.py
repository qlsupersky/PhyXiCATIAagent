"""Selected stdio MCP migration. No model credentials or unrelated settings copied.

Requires Python 3.11+ and tomlkit. Backups stay beside the protected user config,
never in a distributable package. Rollback restores only unchanged managed MCPs.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import tomllib
import tomlkit

NAMES = ('native-modeling', 'catia-v5')
ENV_KEYS = {'PHYXI_NATIVE_WORKSPACE', 'PHYXI_NATIVE_GATE', 'CATIA_MCP_LOG_FILE'}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def atomic_write(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def read_selected(path):
    root = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    servers = root.get('mcpServers', root.get('mcp', {}))
    servers = servers.get('servers', servers)
    selected = {}
    for name in NAMES:
        if name not in servers:
            raise ValueError('Missing selected server: ' + name)
        item = servers[name]
        if item.get('type', 'local') not in ('local', 'stdio'):
            raise ValueError('Selected CATIA servers must use stdio: ' + name)
        command = item.get('command')
        if isinstance(command, list):
            if not command or not all(isinstance(s, str) for s in command):
                raise ValueError('Invalid command array: ' + name)
            executable, args = command[0], command[1:]
        elif isinstance(command, str) and command:
            executable, args = command, item.get('args', [])
        else:
            raise ValueError('Invalid command: ' + name)
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise ValueError('Invalid argument list: ' + name)
        environment = item.get('environment', item.get('env', {}))
        if set(environment) - ENV_KEYS:
            raise ValueError('Unexpected environment keys; review locally before migrating ' + name)
        if not all(isinstance(v, str) for v in environment.values()):
            raise ValueError('Environment values must be strings')
        for key in ('PHYXI_NATIVE_WORKSPACE', 'PHYXI_NATIVE_GATE'):
            if not environment.get(key):
                raise ValueError('Missing required execution context: ' + key)
        selected[name] = {
            'command': executable, 'args': args,
            'env': dict(environment),
            'enabled': item.get('enabled', not item.get('disabled', False)),
            'startup_timeout_sec': 60.0,
            # Codex may time out first; a timeout never proves CAD completed.
            'tool_timeout_sec': 7200.0,
        }
    if selected[NAMES[0]]['env']['PHYXI_NATIVE_GATE'] != selected[NAMES[1]]['env']['PHYXI_NATIVE_GATE']:
        raise ValueError('Both servers must use the same shared CATIA gate')
    if selected[NAMES[0]]['env']['PHYXI_NATIVE_WORKSPACE'] != selected[NAMES[1]]['env']['PHYXI_NATIVE_WORKSPACE']:
        raise ValueError('Both servers must use the same workspace')
    return selected


def migrate(source, config, apply=False):
    selected = read_selected(source)
    config = Path(config)
    before = config.read_bytes() if config.exists() else b''
    doc = tomlkit.parse(before.decode('utf-8-sig'))
    old = tomllib.loads(before.decode('utf-8-sig')).get('mcp_servers', {})
    changes = {n: v for n, v in selected.items() if old.get(n) != v}
    result = {'mode': 'apply' if apply else 'dry-run', 'changed_servers': list(changes),
              'config': str(config), 'model_configuration_changed': False}
    if not apply or not changes:
        return result
    if 'mcp_servers' not in doc:
        doc['mcp_servers'] = tomlkit.table()
    previous = {}
    for name, value in changes.items():
        previous[name] = old.get(name)
        doc['mcp_servers'][name] = value
    after = tomlkit.dumps(doc).encode('utf-8')
    assert tomllib.loads(after.decode())['mcp_servers'] == {**old, **selected}
    folder = config.parent / 'phyxi-backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder.mkdir(parents=True)
    # Contains the user's full original configuration. Keep under Codex home.
    (folder / 'config.before.toml').write_bytes(before)
    receipt = {'version': 1, 'config': str(config.resolve()), 'before_sha256': digest(before),
               'after_sha256': digest(after), 'previous_servers': previous,
               'installed_servers': changes}
    receipt_path = folder / 'migration.json'
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    if (config.read_bytes() if config.exists() else b'') != before:
        raise RuntimeError('Config changed concurrently; no write performed')
    atomic_write(config, after)
    result['rollback_receipt'] = str(receipt_path)
    return result


def rollback(receipt_path):
    receipt = json.loads(Path(receipt_path).read_text(encoding='utf-8'))
    path = Path(receipt['config'])
    raw = path.read_bytes()
    doc = tomlkit.parse(raw.decode('utf-8-sig'))
    current = tomllib.loads(raw.decode('utf-8-sig')).get('mcp_servers', {})
    for name, installed in receipt['installed_servers'].items():
        if current.get(name) != installed:
            raise RuntimeError('Managed server changed since migration; refusing rollback: ' + name)
    for name, previous in receipt['previous_servers'].items():
        if previous is None:
            del doc['mcp_servers'][name]
        else:
            doc['mcp_servers'][name] = previous
    if path.read_bytes() != raw:
        raise RuntimeError('Config changed concurrently; no rollback performed')
    atomic_write(path, tomlkit.dumps(doc).encode('utf-8'))
    return {'rolled_back': list(receipt['installed_servers']), 'unrelated_settings_preserved': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--config', type=Path, default=Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')) / 'config.toml')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--rollback', type=Path)
    args = parser.parse_args()
    if args.rollback:
        if args.source or args.apply:
            parser.error('--rollback cannot be combined with --source/--apply')
        result = rollback(args.rollback)
    else:
        if not args.source:
            parser.error('--source is required')
        result = migrate(args.source, args.config, args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
