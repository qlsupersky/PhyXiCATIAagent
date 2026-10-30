"""Bounded immutable image inputs for the tested OpenCode 2.0.20 files API."""
import base64
from dataclasses import dataclass
import io
import json
import re
from pathlib import Path
import warnings
from PIL import Image
from native_contract import sha

MAX_IMAGES = 4
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_PIXELS = 16000000


@dataclass(frozen=True)
class ImageInput:
    data: bytes
    mime: str
    filename: str
    source_sha256: str = ''
    source_size: tuple = ()
    transform: str = ''


def manifest(images=(), *, _source=False):
    images = tuple(images)
    if len(images) > MAX_IMAGES:
        raise ValueError('最多附加4张PNG/JPEG参考图')
    result = []
    for image in images:
        if not isinstance(image, ImageInput) or not isinstance(image.data, bytes):
            raise ValueError('图片必须为不可变字节快照')
        if (not image.filename or len(image.filename) > 128 or
                any(c in image.filename for c in '/\\:') or any(ord(c) < 32 for c in image.filename)):
            raise ValueError('图片名称须为不含路径的简短文件名')
        signature = {'image/png': b'\x89PNG\r\n\x1a\n', 'image/jpeg': b'\xff\xd8\xff'}
        if image.mime not in signature or not image.data.startswith(signature[image.mime]):
            raise ValueError('仅支持内容与类型相符的PNG/JPEG')
        if len(image.data) > MAX_IMAGE_BYTES:
            raise ValueError('单图不能超过8MiB')
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(image.data)) as decoded:
                if decoded.width * decoded.height > MAX_PIXELS or getattr(decoded, 'n_frames', 1) != 1:
                    raise ValueError('参考图须为不超过1600万像素的单帧图片')
                if decoded.format != ('PNG' if image.mime == 'image/png' else 'JPEG'):
                    raise ValueError('图片解码格式不符')
                size = list(decoded.size)
                decoded.verify()
        if not _source and (max(size) > 2000 or len(image.data) > 3*1024*1024):
            raise ValueError('模型图片超过接口限制，请通过“添加参考图”读取以生成缩放快照')
        item = {'filename': image.filename, 'mime': image.mime, 'bytes': len(image.data), 'sha256': sha(image.data), 'size': size}
        if image.transform:
            if (not re.fullmatch(r'[0-9a-f]{64}', image.source_sha256) or len(image.source_size) != 2 or
                    image.transform != 'fit1920_jpeg_white' or any(type(n) is not int or n <= 0 for n in image.source_size)):
                raise ValueError('图片转换清单不符')
            item.update(source_sha256=image.source_sha256, source_size=list(image.source_size), transform=image.transform)
        result.append(item)
    if sum(item['bytes'] for item in result) > MAX_TOTAL_BYTES:
        raise ValueError('图片合计不能超过16MiB')
    return result


def from_path(path):
    path = Path(path)
    # Limit before reading potentially oversized files. Revalidate actual bytes.
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError('单图不能超过8MiB')
    raw = path.read_bytes()
    mime = 'image/png' if raw.startswith(b'\x89PNG\r\n\x1a\n') else 'image/jpeg'
    result = ImageInput(raw, mime, path.name)
    original = manifest([result], _source=True)[0]
    if max(original['size']) > 2000 or len(raw) > 3*1024*1024:
        # OpenCode 2.0.20 actually rejects a >2000px side before persisting the
        # message. Explicitly transform locally; never claim original bytes sent.
        with Image.open(io.BytesIO(raw)) as picture:
            picture.load();picture.thumbnail((1920,1920),Image.Resampling.LANCZOS)
            rgba=picture.convert('RGBA');flat=Image.new('RGB',rgba.size,'white');flat.paste(rgba,mask=rgba.getchannel('A'))
            for quality in (85,70,55,40):
                out=io.BytesIO();flat.save(out,format='JPEG',quality=quality,optimize=True)
                converted=out.getvalue()
                if len(converted) <= 3*1024*1024:break
            else:raise ValueError('缩放后图片仍过大，请选择更小参考图')
        result=ImageInput(converted,'image/jpeg',path.stem[:90]+'.model.jpg',sha(raw),tuple(original['size']),'fit1920_jpeg_white')
    manifest([result])
    return result


def input_hash(requirement, images_manifest):
    return sha(json.dumps({'requirement': requirement, 'reference_images': images_manifest},
                         sort_keys=True, ensure_ascii=False).encode())


def prompt_body(text, images=()):
    info = manifest(images)
    body = {'text': text}
    if info:
        body['files'] = [{'uri': 'data:' + im.mime + ';base64,' + base64.b64encode(im.data).decode('ascii'),
                          'mime': im.mime, 'filename': im.filename} for im in images]
    return body, info


def verify_stored(rows, body):
    """One fresh session per prompt. Byte persistence is distinct from vision accuracy."""
    users = [r for r in rows if r.get('type') == 'user']
    if len(users) != 1 or users[0].get('text') != body['text']:
        raise ValueError('无法绑定本轮图片请求与实际会话')
    requested = body.get('files', [])
    stored = users[0].get('files', [])
    if len(requested) != len(stored):
        raise ValueError('实际会话图片数量不符')
    observed = []
    for source, actual in zip(requested, stored):
        want = base64.b64decode(source['uri'].split(',', 1)[1], validate=True)
        got = base64.b64decode(actual['data'], validate=True)
        if actual['mime'] != source['mime'] or actual['source']['type'] != 'inline' or got != want:
            raise ValueError('实际会话图片字节不符；未接受结果')
        observed.append({'sha256': sha(got), 'bytes': len(got), 'mime': actual['mime']})
    assistants = [r for r in rows if r.get('type') == 'assistant']
    if not assistants:
        raise ValueError('缺少真实模型答复')
    for row in assistants:
        model = row.get('model', {})
        if model.get('providerID') != 'phyxi-deepseek' or model.get('id') != 'deepseek-flash' or row.get('error'):
            raise ValueError('实际答复模型不符合当前连接或本轮失败')
    if sum(r.get('finish') == 'stop' for r in assistants) != 1:
        raise ValueError('缺少唯一完成答复')
    return {'user_id': users[0]['id'], 'model': 'deepseek-flash', 'provider': 'phyxi-deepseek',
            'images_persisted': observed, 'scope': 'byte persistence and model identity; not visual accuracy or CAD acceptance'}


def load_snapshot(folder, expected):
    folder = Path(folder)
    actual = json.loads((folder / 'image-manifest.json').read_text(encoding='utf-8'))
    if actual != expected:
        raise ValueError('参考图清单已变，需重新生成和审阅')
    images = []
    for i, item in enumerate(actual, 1):
        images.append(ImageInput((folder / 'attachments' / (str(i) + '.bin')).read_bytes(), item['mime'], item['filename'],
                                 item.get('source_sha256',''),tuple(item.get('source_size',())),item.get('transform','')))
    if manifest(images) != expected:
        raise ValueError('参考图快照已变，需重新生成和审阅')
    return images
