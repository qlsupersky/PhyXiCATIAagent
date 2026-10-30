"""Local session persistence without model credentials or endpoint configuration."""
from pathlib import Path
from datetime import datetime
import json
import os
import re
import uuid


class Sessions:
    def __init__(self, workspace):
        self.folder = Path(workspace)/"sessions"
        self.folder.mkdir(parents=True, exist_ok=True)

    def save(self, session_id, messages, transcript, secret=""):
        session_id = session_id or uuid.uuid4().hex
        if not re.fullmatch(r"[a-f0-9]{32}", session_id):
            raise ValueError("非法会话标识")
        value = {"schema": "phyxi-session-1", "id": session_id, "updated": datetime.now().isoformat(timespec="seconds"),
                 "messages": messages, "transcript": transcript}
        rendered = json.dumps(value, ensure_ascii=False, indent=2)
        if secret:
            rendered = rendered.replace(json.dumps(secret, ensure_ascii=False)[1:-1], "[API_KEY_REDACTED]")
        temporary = self.folder/(session_id+".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        os.replace(temporary, self.folder/(session_id+".json"))
        return session_id

    def load(self, path):
        path = Path(path).resolve()
        if path.parent != self.folder.resolve() or not re.fullmatch(r"[a-f0-9]{32}\.json", path.name):
            raise ValueError("只能打开本插件 sessions 目录内的会话")
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("schema") != "phyxi-session-1" or not isinstance(value.get("messages"), list):
            raise ValueError("会话格式不兼容")
        if any(m.get("role") not in ("user", "assistant", "tool") for m in value["messages"]):
            raise ValueError("会话包含不支持的角色")
        return value
