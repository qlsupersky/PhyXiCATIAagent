import json
from pathlib import Path
import tempfile
import tomllib
import unittest

from migrate_mcp import migrate, read_selected, rollback
from package_extension import build


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'opencode.json'
        self.config = self.root / 'config.toml'
        self.servers = {name: {'type': 'local', 'command': ['python', name + '.py'],
            'environment': {'PHYXI_NATIVE_WORKSPACE': 'workspace', 'PHYXI_NATIVE_GATE': 'shared.sqlite'}}
            for name in ('native-modeling', 'catia-v5')}
        self.write_source()
        self.original = '# retain comment\nmodel = "keep-model"\n[model_providers.private]\nbase_url = "private"\n[mcp_servers.other]\ncommand = "keep"\n'
        self.config.write_text(self.original, encoding='utf-8')

    def write_source(self):
        self.source.write_text(json.dumps({'mcp': self.servers, 'provider': {'secret': 'DO_NOT_COPY'}}), encoding='utf-8')

    def test_dry_run_is_read_only(self):
        self.assertEqual(len(migrate(self.source, self.config)['changed_servers']), 2)
        self.assertEqual(self.config.read_text(), self.original)
        self.assertFalse((self.root / 'phyxi-backups').exists())

    def test_preserve_settings_and_idempotence(self):
        migrate(self.source, self.config, True)
        raw = self.config.read_text()
        self.assertIn('# retain comment', raw)
        doc = tomllib.loads(raw)
        self.assertEqual(doc['model'], 'keep-model')
        self.assertEqual(doc['model_providers']['private']['base_url'], 'private')
        self.assertEqual(doc['mcp_servers']['other']['command'], 'keep')
        self.assertNotIn('DO_NOT_COPY', raw)
        self.assertEqual(migrate(self.source, self.config, True)['changed_servers'], [])

    def test_rollback_keeps_later_unrelated_changes(self):
        receipt = migrate(self.source, self.config, True)['rollback_receipt']
        with self.config.open('a') as stream:
            stream.write('\n[new_feature]\nenabled = true\n')
        rollback(receipt)
        doc = tomllib.loads(self.config.read_text())
        self.assertTrue(doc['new_feature']['enabled'])
        self.assertEqual(list(doc['mcp_servers']), ['other'])

    def test_rollback_refuses_changed_managed_server(self):
        receipt = migrate(self.source, self.config, True)['rollback_receipt']
        self.config.write_text(self.config.read_text().replace('7200.0', '7201.0'))
        with self.assertRaises(RuntimeError):
            rollback(receipt)

    def test_refuse_mismatched_gate(self):
        self.servers['catia-v5']['environment']['PHYXI_NATIVE_GATE'] = 'different'
        self.write_source()
        with self.assertRaises(ValueError):
            read_selected(self.source)

    def test_refuse_secret_environment(self):
        self.servers['catia-v5']['environment']['API_KEY'] = 'secret'
        self.write_source()
        with self.assertRaises(ValueError):
            read_selected(self.source)

    def test_refuse_missing_server(self):
        del self.servers['catia-v5']
        self.write_source()
        with self.assertRaises(ValueError):
            read_selected(self.source)

    def test_packages_are_distinct_and_refuse_overwrite(self):
        plain = self.root / 'plain'
        build(plain)
        manifest = json.loads((plain / 'plugins/phyxi-catia/.codex-plugin/plugin.json').read_text())
        self.assertNotIn('mcpServers', manifest)
        bundled = self.root / 'bundled'
        build(bundled, self.source)
        servers = json.loads((bundled / 'plugins/phyxi-catia/.mcp.json').read_text())['mcpServers']
        self.assertEqual(set(servers), set(self.servers))
        with self.assertRaises(FileExistsError):
            build(plain)
        skill = self.root / 'skill'
        build(skill, standalone=True)
        self.assertTrue((skill / 'SKILL.md').is_file())


if __name__ == '__main__':
    unittest.main()
