"""Read-only local design text import. Embedded instructions remain untrusted data."""
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET
import hashlib

MAX_BYTES = 10 * 1024 * 1024
MAX_CHARS = 60000


def load_design(path):
    path = Path(path).resolve()
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("设计文档超过 10 MB，请先拆分")
    pictures = 0
    if path.suffix.lower() == ".docx":
        with ZipFile(path) as archive:
            entries = [e for e in archive.infolist() if e.filename == "word/document.xml"]
            if len(entries) != 1 or entries[0].file_size > MAX_BYTES:
                raise ValueError("DOCX 正文缺失或过大")
            root = ET.fromstring(archive.read(entries[0]))
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            paragraphs = ["".join(t.text or "" for t in p.findall(".//w:t", ns)) for p in root.findall(".//w:p", ns)]
            text = "\n".join(paragraphs)
            pictures = sum(e.filename.startswith("word/media/") for e in archive.infolist())
    elif path.suffix.lower() in (".txt", ".md", ".json"):
        text = path.read_text(encoding="utf-8-sig")
    else:
        raise ValueError("当前支持 DOCX 正文、UTF-8 TXT/MD/JSON；不支持扫描图、PDF OCR 或自动读取 CATPart 几何")
    if len(text) > MAX_CHARS:
        raise ValueError("设计正文超过 60000 字符，请拆分后导入；未自动截断")
    if not text.strip():
        raise ValueError("文档没有可读取正文")
    return {"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "text": text, "embedded_images": pictures,
            "note": "仅提取正文及表格文字；图片中的参数未识别，需人工补充" if pictures else "正文已读取"}
