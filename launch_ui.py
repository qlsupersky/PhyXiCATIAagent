"""Launch the browser/Electron workspace without changing CATIA or active sessions."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def launch(mode):
    config = json.loads((ROOT / 'config.json').read_text(encoding='utf-8-sig')) if (ROOT / 'config.json').exists() else {}
    workspace = Path(config.get('workspace', str(Path.home() / 'Documents/PhyXiCATIAAgent')))
    if mode == 'web':
        logs = workspace / 'webui'; logs.mkdir(parents=True, exist_ok=True)
        with (logs / 'server.log').open('a', encoding='utf-8') as out:
            return subprocess.Popen([sys.executable, str(ROOT / 'web_server.py'), '--browser', '--workspace', str(workspace)],
                cwd=ROOT, stdout=out, stderr=out, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).pid
    candidate = Path(config.get('electron_executable', str(ROOT / 'desktop/node_modules/electron/dist/electron.exe')))
    if not candidate.is_file(): raise RuntimeError('请先运行 install-desktop.ps1 安装 Electron 运行时，再使用桌面工作台')
    env = {**os.environ, 'PHYXI_PYTHON': config.get('python', sys.executable)}
    return subprocess.Popen([str(candidate), str(ROOT / 'desktop')], cwd=ROOT, env=env,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).pid


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('mode', choices=('web','desktop'))
    args = parser.parse_args()
    try: launch(args.mode)
    except Exception as error:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk(); root.withdraw(); messagebox.showerror('PhyXi', str(error)); root.destroy()
        raise SystemExit(1)
