"""Load the independent DeepSeek credential encrypted for this Windows user."""
import json
from pathlib import Path
from providers import PROVIDERS, DEEPSEEK_BASE, DEEPSEEK_MODEL, endpoint


def load_deepseek(config_path=None):
    import win32crypt
    path = Path(config_path) if config_path else Path(__file__).with_name('config.json')
    config = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
    base = config.get('deepseek_base_url', DEEPSEEK_BASE)
    model = config.get('deepseek_model', DEEPSEEK_MODEL)
    endpoint(base, model, PROVIDERS[5], resolve=False)
    credential = Path.home()/'Documents/PhyXiCATIAAgent/credentials/deepseek.dpapi'
    try:
        key = win32crypt.CryptUnprotectData(credential.read_bytes(), None, None, None, 0)[1].decode()
    except Exception:
        raise ValueError('未找到当前 Windows 用户的 DeepSeek 加密凭据，请在面板填写 API Key') from None
    return dict(provider=PROVIDERS[5], base_url=base, model=model, key=key)
