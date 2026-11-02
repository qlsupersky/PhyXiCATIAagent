import importlib.util
from pathlib import Path
import tempfile
import unittest
import os

spec = importlib.util.spec_from_file_location('embedded_probe', Path(__file__).resolve().parents[1] / 'probe_environment.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def temporary():
    root = os.environ.get('PHYXI_TEST_WORK')
    if root: Path(root).mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(dir=root)


class EnvironmentPreflight(unittest.TestCase):
    def test_runtime_is_not_an_sdk(self):
        with temporary() as folder:
            root = Path(folder); target = root / 'win_b64/code/bin'
            target.mkdir(parents=True); (target / 'CNEXT.exe').write_bytes(b'placeholder')
            result = module.probe(root, find_tool=lambda _: None)
            self.assertTrue(result['checks']['catia_runtime'])
            self.assertFalse(result['can_attempt_caa_build'])
            self.assertEqual(len(result['missing_headers']), 8)
            self.assertFalse(result['loaded_in_catia'])

    def test_found_prerequisites_do_not_claim_a_build_or_license(self):
        with temporary() as folder:
            root = Path(folder); target = root / 'win_b64/code/bin'
            target.mkdir(parents=True); (target / 'CNEXT.exe').write_bytes(b'placeholder')
            sdk = root / 'sdk'; sdk.mkdir()
            for name in module.HEADERS: (sdk / name).write_text('// test fixture')
            for name in module.LIBRARIES: (sdk / name).write_bytes(b'placeholder')
            result = module.probe(root, sdk=sdk, find_tool=lambda name: 'fixture-' + name)
            self.assertTrue(result['can_attempt_caa_build'])
            self.assertFalse(result['caa_module_compiled'])
            self.assertEqual(result['compiler_abi_and_license_validation'], 'NOT_CHECKED')

    def test_headers_without_toolchain_are_blocked(self):
        with temporary() as folder:
            root = Path(folder)
            for name in module.HEADERS: (root / name).write_text('// test fixture')
            result = module.probe(root, sdk=root, find_tool=lambda _: None)
            self.assertEqual(result['missing_headers'], [])
            self.assertFalse(result['can_attempt_caa_build'])


if __name__ == '__main__': unittest.main()
