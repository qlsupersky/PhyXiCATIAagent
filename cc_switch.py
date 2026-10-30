"""Read an explicitly pinned or current Micu connection; never write the CC Switch DB."""
import json
import sqlite3
try:
    import tomllib
except ImportError:
    import tomli as tomllib
from pathlib import Path
from providers import PROVIDERS, endpoint


def load_micu(path=None, provider_id=None):
    path = Path(path) if path else Path.home()/'.cc-switch/cc-switch.db'
    try:
        connection = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)
        try:
            if provider_id is not None:
                if not isinstance(provider_id, str) or not provider_id.strip():
                    raise ValueError('CC Switch连接ID不能为空')
                rows = connection.execute("SELECT settings_config FROM providers WHERE app_type='codex' AND id=?", (provider_id,)).fetchall()
            else:
                rows = connection.execute("SELECT settings_config FROM providers WHERE app_type='codex' AND is_current=1").fetchall()
        finally:
            connection.close()
        if len(rows) != 1:
            raise ValueError('找不到唯一的CC Switch指定连接；未改用其他供应商')
        settings = json.loads(rows[0][0])
        config = tomllib.loads(settings['config'])
        selected = config['model_providers'][config['model_provider']]
        if selected.get('wire_api') != 'responses':
            raise ValueError('当前CC Switch连接不是Responses接口')
        base, model = selected['base_url'], config['model']
        endpoint(base, model, PROVIDERS[3], resolve=False)
        key = settings.get('auth', {}).get('OPENAI_API_KEY', '')
        if not isinstance(key, str) or not key.strip():
            raise ValueError('CC Switch当前米醋配置未保存可用密钥；请在面板内填写')
        return {'provider': PROVIDERS[3], 'base_url': base, 'model': model, 'key': key}
    except (OSError, sqlite3.Error, KeyError, TypeError, json.JSONDecodeError, tomllib.TOMLDecodeError):
        raise ValueError('无法读取CC Switch当前米醋配置；请在面板手动填写连接信息') from None
