"""Read a Windows-user-encrypted credential for the explicit server connection."""
import json
from pathlib import Path
from providers import PROVIDERS,endpoint

def load_server(config_path=None):
    import win32crypt
    config_path=Path(config_path) if config_path else Path(__file__).with_name('config.json')
    config=json.loads(config_path.read_text(encoding='utf-8-sig'))
    base=config.get('server_base_url','http://127.0.0.1:8000/v1')
    model=config.get('server_model','qwen3.8-base')
    endpoint(base,model,PROVIDERS[4],resolve=False)
    path=Path.home()/'Documents/PhyXiCATIAAgent/credentials/qwen-base.dpapi'
    try:key=win32crypt.CryptUnprotectData(path.read_bytes(),None,None,None,0)[1].decode()
    except Exception:raise ValueError('未找到当前Windows用户的加密服务器凭据，请在面板填写API Key') from None
    return dict(provider=PROVIDERS[4],base_url=base,model=model,key=key)
