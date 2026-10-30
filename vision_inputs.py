"""Attach only verified PNGs produced by a successful local section-analysis run."""
import base64
import hashlib
import json
from pathlib import Path


def section_image_message(result, workspace):
    folder=Path(result['evidence']).resolve().parent
    workspace=Path(workspace).resolve()
    if not folder.is_relative_to(workspace/'section-analysis'):
        raise ValueError('截面图片必须来自当前插件工作目录')
    saved=json.loads((folder/'analysis.json').read_text(encoding='utf-8'))
    if saved.get('source_sha256')!=result['source_sha256'] or saved.get('images')!=result.get('images'):
        raise ValueError('截面图片与分析记录不一致')
    blocks=[{'type':'text','text':'以下是刚才 analyze_surface_sections 为当前零件生成的实际图片。请结合几何工具结果识图，说明观察方向、可见证据、盲区及不确定性。不要把颜色、文字标注或文件名当成独立识别结果；不要把截面缺口直接当成孔数。'}]
    total=0
    for name in result['images']:
        path=Path(name).resolve()
        if path.parent!=folder or path.name not in ('sections.png','sections-detail.png','geometry-overview.png','curvature-map.png','catia-viewport.png'):
            raise ValueError('不支持的截面图片')
        data=path.read_bytes();total+=len(data)
        if hashlib.sha256(data).hexdigest()!=saved['image_sha256'][path.name]:
            raise ValueError('截面图片在分析后已改变，请重新生成')
        if not data.startswith(b'\x89PNG\r\n\x1a\n') or total>8*1024*1024:
            raise ValueError('截面图片格式无效或超过8MB')
        blocks.append({'type':'text','text':f'{path.name}; sha256={hashlib.sha256(data).hexdigest()}'})
        blocks.append({'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(data).decode('ascii'),'detail':'high'}})
    return {'role':'user','content':blocks}
