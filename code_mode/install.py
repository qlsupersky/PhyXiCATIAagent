"""Install only the Code Mode facade in Codex; preserve existing model settings.

Existing direct CATIA registrations are disabled, not deleted; OpenCode is kept.
Default dry run. Protected backup enables conflict-aware selective rollback.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tomllib
import tomlkit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'codex'))
from migrate_mcp import atomic_write, read_selected

MANAGED = ('catia-code', 'native-modeling', 'catia-v5')


def install(source, config, node, python, apply=False):
    root = Path(__file__).resolve().parent
    config = Path(config)
    node, python = Path(node).resolve(), Path(python).resolve()
    if not node.is_file() or not python.is_file():
        raise ValueError('Node/Python executables not found')
    if not (root / 'runtime/node_modules/quickjs-emscripten/package.json').is_file():
        raise ValueError('Run npm ci --ignore-scripts in code_mode/runtime first')
    selected = read_selected(source)
    raw = config.read_bytes()
    data = tomllib.loads(raw.decode('utf-8-sig'))
    doc = tomlkit.parse(raw.decode('utf-8-sig'))
    servers = doc.setdefault('mcp_servers', tomlkit.table())
    prior = {n: data.get('mcp_servers', {}).get(n) for n in MANAGED}
    backend_path = config.parent / 'phyxi-code-mode/backends.json'
    for name in ('native-modeling', 'catia-v5'):
        if name in servers:
            servers[name]['enabled'] = False
    servers['catia-code'] = {'command': str(python), 'args': [str(root / 'server.py')],
        'env': {'PHYXI_PTC_BACKENDS': str(backend_path), 'PHYXI_PTC_NODE': str(node)},
        'enabled': True, 'startup_timeout_sec': 60, 'tool_timeout_sec': 120}
    after = tomlkit.dumps(doc).encode('utf-8')
    installed = {n: tomllib.loads(after.decode())['mcp_servers'].get(n) for n in MANAGED}
    # No unrelated model/provider/plugin changes.
    a, b = data.copy(), tomllib.loads(after.decode())
    for obj in (a, b):
        obj['mcp_servers'] = {k: v for k, v in obj.get('mcp_servers', {}).items() if k not in MANAGED}
    assert a == b
    local_backend = {n: {k: selected[n][k] for k in ('command', 'args', 'env')} for n in selected}
    result = {'mode': 'apply' if apply else 'dry-run', 'direct_servers_disabled': ['native-modeling', 'catia-v5'],
        'code_facade': 'catia-code', 'tools_exposed': 3, 'model_settings_changed': False,
        'OpenCode_configuration_changed': False}
    if not apply:
        return result
    folder = config.parent / 'phyxi-backups' / ('ptc-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    folder.mkdir(parents=True)
    (folder / 'config.before.toml').write_bytes(raw)
    backend_before = backend_path.read_bytes() if backend_path.exists() else None
    if backend_before is not None:
        (folder / 'backends.before.json').write_bytes(backend_before)
    receipt = {'config': str(config), 'previous': prior, 'installed': installed, 'backend_path': str(backend_path),
        'backend_sha256': hashlib.sha256(encode_backend(local_backend)).hexdigest(),
        'backup_backend': str(folder / 'backends.before.json') if backend_before is not None else None}
    receipt_path = folder / 'ptc-install.json'
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    if config.read_bytes() != raw:
        raise RuntimeError('Configuration changed concurrently')
    atomic_write(backend_path, encode_backend(local_backend))
    atomic_write(config, after)
    result['rollback_receipt'] = str(receipt_path)
    return result


def encode_backend(value):
    return json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8')


def rollback(receipt_path):
    receipt = json.loads(Path(receipt_path).read_text(encoding='utf-8'))
    config = Path(receipt['config'])
    raw = config.read_bytes()
    doc = tomlkit.parse(raw.decode('utf-8-sig'))
    current = tomllib.loads(raw.decode('utf-8-sig')).get('mcp_servers', {})
    if any(current.get(n) != value for n, value in receipt['installed'].items()):
        raise RuntimeError('Managed configuration changed; refusing overwrite')
    for name, old in receipt['previous'].items():
        if old is None:
            if name in doc['mcp_servers']: del doc['mcp_servers'][name]
        else:
            doc['mcp_servers'][name] = old
    backend = Path(receipt['backend_path'])
    if backend.exists() and hashlib.sha256(backend.read_bytes()).hexdigest() != receipt['backend_sha256']:
        raise RuntimeError('Backend configuration changed; refusing overwrite')
    if config.read_bytes() != raw:
        raise RuntimeError('Configuration changed concurrently')
    atomic_write(config, tomlkit.dumps(doc).encode('utf-8'))
    if receipt['backup_backend']:
        atomic_write(backend, Path(receipt['backup_backend']).read_bytes())
    # Keep backend configuration when originally absent, for old in-flight readers.
    return {'rolled_back': list(MANAGED), 'unrelated_settings_preserved': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--config', type=Path, default=Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')) / 'config.toml')
    parser.add_argument('--node', default=shutil.which('node'))
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--rollback', type=Path)
    args = parser.parse_args()
    if args.rollback:
        result = rollback(args.rollback)
    else:
        if not args.source:
            parser.error('--source required')
        result = install(args.source, args.config, args.node, args.python, args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))
