import json
import os
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from install import install, rollback


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source.json'
        self.config = self.root / 'config.toml'
        self.original = ('model = "keep-model"\n[model_providers.private]\nname="keep"\n'
            '[mcp_servers.native-modeling]\ncommand="old-native"\nenabled=true\n'
            '[mcp_servers.catia-v5]\ncommand="old-catia"\nenabled=true\n'
            '[mcp_servers.other]\ncommand="keep-other"\n')
        self.config.write_text(self.original, encoding='utf-8')
        self.source.write_text(json.dumps({'mcp': {n: {'command': [sys.executable, 'backend.py'],
            'environment': {'PHYXI_NATIVE_GATE': 'shared-gate', 'PHYXI_NATIVE_WORKSPACE': 'shared-workspace'}}
            for n in ('native-modeling', 'catia-v5')}}), encoding='utf-8')
        self.node = os.environ.get('PHYXI_PTC_TEST_NODE', sys.executable)

    def apply(self, apply=True):
        return install(self.source, self.config, self.node, sys.executable, apply)

    def test_dryrun_no_writes(self):
        result = self.apply(False)
        self.assertEqual(result['mode'], 'dry-run')
        self.assertEqual(self.config.read_text(encoding='utf-8'), self.original)
        self.assertFalse((self.root / 'phyxi-backups').exists())

    def test_apply_and_selective_rollback(self):
        result = self.apply()
        data = tomllib.loads(self.config.read_text(encoding='utf-8'))
        self.assertEqual(data['model'], 'keep-model')
        self.assertFalse(data['mcp_servers']['catia-v5']['enabled'])
        self.assertTrue(data['mcp_servers']['catia-code']['enabled'])
        self.config.write_text(self.config.read_text(encoding='utf-8').replace('keep-model', 'new-model'), encoding='utf-8')
        rollback(result['rollback_receipt'])
        data = tomllib.loads(self.config.read_text(encoding='utf-8'))
        self.assertEqual(data['model'], 'new-model')
        self.assertEqual(data['mcp_servers']['native-modeling']['command'], 'old-native')
        self.assertNotIn('catia-code', data['mcp_servers'])

    def test_rollback_conflict_refused(self):
        result = self.apply()
        self.config.write_text(self.config.read_text(encoding='utf-8').replace('old-catia', 'edited'), encoding='utf-8')
        with self.assertRaises(RuntimeError): rollback(result['rollback_receipt'])

    def test_foreign_environment_refused(self):
        data = json.loads(self.source.read_text(encoding='utf-8'))
        data['mcp']['catia-v5']['environment']['API_KEY'] = 'not-a-secret-test'
        self.source.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ValueError): self.apply()


if __name__ == '__main__': unittest.main()
