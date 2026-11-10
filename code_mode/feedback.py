"""Bound result feedback; never makes a CAD call or reads arbitrary tool paths."""
import base64
import hashlib
import json
from pathlib import Path
import re
import shutil


def native_feedback(data, workspace, evidence):
    if not isinstance(data, dict) or not re.fullmatch(r'native-[0-9a-f]{24}', data.get('job_id', '')):
        return None
    job = data['job_id']
    failed = data.get('state') == 'FAILED' or data.get('passed') is False
    observed = data.get('reopened_readback') or data.get('readback') or {}
    diagnostic = data.get('diagnostic') or {}
    final = data.get('final') or {}
    feedback = {'job_id': job, 'source': 'native_executor_bound_readback',
        'passed': not failed and final.get('passed') is True,
        'reason': data.get('reason', 'readback_passed' if final.get('passed') else 'no_final_acceptance'),
        'observed': {k: observed.get(k) for k in ('features', 'sketch_count', 'body_count', 'volume_mm3',
            'expected_volume_mm3', 'volume_match', 'saved') if k in observed},
        'image_available': False, 'visual_interpretation_performed': False}
    if data.get('script_error'):
        feedback['script_error'] = str(data['script_error'])[:2000]
    if diagnostic:
        feedback['diagnostic_reason'] = diagnostic.get('reason')
    volume, expected = observed.get('volume_mm3'), observed.get('expected_volume_mm3')
    if isinstance(volume, (float, int)) and isinstance(expected, (float, int)):
        feedback['volume_delta_mm3'] = volume - expected
        if expected: feedback['volume_relative_error'] = (volume - expected) / expected
    # Only accept the executor's fixed own-job file + digest, never an arbitrary path.
    container = diagnostic if failed else final
    name = 'FAILED-CANDIDATE.jpg' if failed else 'RESULT.jpg'
    root = Path(workspace).resolve() / 'native-modeling/jobs'
    folder = root / job
    image_path = folder / name
    supplied = container.get('image')
    digest = container.get('image_sha256')
    try:
        if (supplied and digest and Path(supplied).resolve() == image_path.resolve()
                and not folder.is_symlink() and not image_path.is_symlink()
                and not folder.is_junction() and not image_path.is_junction()
                and folder.resolve().parent == root.resolve()
                and image_path.is_file() and 0 < image_path.stat().st_size <= 8 * 1024 * 1024
                and hashlib.sha256(image_path.read_bytes()).hexdigest() == digest):
            target = Path(evidence) / 'feedback.jpg'
            shutil.copyfile(image_path, target)
            feedback.update(image_available=True, image_name=target.name, image_sha256=digest)
    except (OSError, ValueError):
        feedback['image_error'] = 'BOUND_IMAGE_UNAVAILABLE'
    return feedback


def finalize_feedback(record):
    value = dict(record.get('feedback') or {})
    value.update(program_status=record['status'], program_error=record.get('error'),
        automatic_retry=False, replay_allowed=False,
        next_action=('Observe original upstream completion; do not dispatch repair.'
            if record['status'] == 'UNCERTAIN' or record.get('observed_upstream_uncertain') else
            'Use mismatch evidence and image if present; correct the program with a NEW request_id.'
            if record['status'] == 'FAILED' else 'Compare observed geometry with the independent task requirements.'))
    if record.get('upstream_failure'):
        value['upstream_failure'] = record['upstream_failure']
    return value


def content_for_status(record, include_feedback=False):
    """Image is returned to the model as MCP ImageContent, not only a pathname."""
    from mcp.types import CallToolResult, TextContent, ImageContent
    content = [TextContent(type='text', text=json.dumps(record, ensure_ascii=False))]
    if include_feedback:
        feedback = record.get('feedback') or {}
        image_path = Path(record.get('evidence_directory', '.')) / 'feedback.jpg'
        try:
            if (feedback.get('image_available') and image_path.is_file()
                    and not image_path.is_symlink() and not image_path.is_junction()
                    and image_path.stat().st_size <= 8 * 1024 * 1024):
                raw = image_path.read_bytes()
                if hashlib.sha256(raw).hexdigest() == feedback.get('image_sha256'):
                    content.append(ImageContent(type='image', data=base64.b64encode(raw).decode('ascii'), mimeType='image/jpeg'))
        except OSError:
            pass
    return CallToolResult(content=content, structuredContent=record)
