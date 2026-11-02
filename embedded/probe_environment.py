"""Read-only CAA preflight. A CATIA runtime is not a CAA SDK.

No module registration, environment-file mutation, CAD call or license bypass.
"""
import argparse
import json
from pathlib import Path
import shutil

HEADERS = ('CATBaseUnknown.h', 'CATDialog.h', 'CATDlgDialog.h',
           'CATApplicationFrame.h', 'CATStateCommand.h', 'CATCreateWorkshop.h',
           'CATIAfrGeneralWksAddin.h', 'TIE_CATIAfrGeneralWksAddin.h')
LIBRARIES = ('JS0GROUP.lib', 'CATApplicationFrame.lib', 'DI0PANV2.lib')


def probe(runtime, sdk=None, find_tool=shutil.which):
    runtime = Path(runtime)
    platform = runtime if runtime.name == 'win_b64' else runtime / 'win_b64'
    level = platform / 'LevelSPK.txt'
    version = level.read_text(encoding='utf-8', errors='replace').strip() if level.exists() else 'unknown'
    roots = [Path(sdk)] if sdk else [runtime]
    found = set()
    libraries = 0
    found_libs = set()
    for root in roots:
        if not root.is_dir(): continue
        for p in root.rglob('*'):
            if not p.is_file(): continue
            if p.name in HEADERS: found.add(p.name)
            if p.suffix.lower() == '.lib':
                libraries += 1
                if p.name in LIBRARIES: found_libs.add(p.name)
    mkmk, compiler = find_tool('mkmk'), find_tool('cl')
    missing = [n for n in HEADERS if n not in found]
    checks = {'catia_runtime': (platform / 'code/bin/CNEXT.exe').is_file(),
              'explicit_sdk_root': bool(sdk and Path(sdk).is_dir()),
              'required_headers': not missing, 'required_import_libraries': set(LIBRARIES) <= found_libs,
              'rade_mkmk': bool(mkmk), 'supported_msvc_environment_available': bool(compiler)}
    ready = all(checks.values())
    return {'schema': 1, 'status': 'PREREQUISITES_FOUND_NOT_YET_BUILT' if ready else 'BLOCKED_MISSING_CAA_DEVELOPMENT_ENVIRONMENT',
            'can_attempt_caa_build': ready, 'catia_runtime_version': version,
            'checks': checks, 'missing_headers': missing, 'import_library_count': libraries,
            'missing_import_libraries': [name for name in LIBRARIES if name not in found_libs],
            'caa_module_compiled': False, 'loaded_in_catia': False,
            'compiler_abi_and_license_validation': 'NOT_CHECKED',
            'native_host_test_does_not_prove_caa_loading': True}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--catia-root', type=Path, required=True)
    p.add_argument('--sdk-root', type=Path)
    p.add_argument('--output', type=Path)
    args = p.parse_args()
    result = probe(args.catia_root, args.sdk_root)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
    print(text)
    return 0 if result['can_attempt_caa_build'] else 2


if __name__ == '__main__': raise SystemExit(main())
