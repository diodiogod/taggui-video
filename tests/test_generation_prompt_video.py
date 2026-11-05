"""Prompt extraction from real video containers and their workflow sidecars."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
from threading import Event

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'taggui'))
from utils import generation_prompt
from utils.generation_prompt import read_generation_prompts


def graph(positive='original input', negative='bad'):
    return {
        '1': {'class_type': 'SimplePromptStandalone', 'inputs': {
            'positive': positive, 'negative': negative}},
        '2': {'class_type': 'CLIPTextEncode', 'inputs': {'text': ['1', 0]}},
        '3': {'class_type': 'KSampler', 'inputs': {'positive': ['2', 0]}},
    }


def make_video(path, tags=None, *, duration=1):
    command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
               '-f', 'lavfi', '-i', f'color=c=red:s=32x32:r=24:d={duration}',
               '-c:v', 'libvpx-vp9' if path.suffix == '.webm' else 'libx264',
               '-pix_fmt', 'yuv420p']
    for key, value in (tags or {}).items():
        command += ['-metadata', f'{key}={value}']
    if path.suffix == '.mp4':
        command += ['-movflags', 'use_metadata_tags']
    command.append(str(path))
    subprocess.run(command, check=True, capture_output=True, timeout=20,
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


requires_ffmpeg = pytest.mark.skipif(
    not shutil.which('ffmpeg') or not shutil.which('ffprobe'),
    reason='Video metadata tests require FFmpeg and FFprobe',
)


@requires_ffmpeg
@pytest.mark.parametrize('suffix', ['.mp4', '.webm'])
def test_video_saver_parameters_outrank_workflow_in_real_container(tmp_path, suffix):
    path = tmp_path / f'clip{suffix}'
    parameters = 'final café\nsecond line\nNegative prompt: blur\nSteps: 20, CFG scale: 5'
    make_video(path, {'parameters': parameters, 'prompt': json.dumps(graph()),
                      'workflow': json.dumps({'nodes': []})})
    before = path.read_bytes()
    result = read_generation_prompts(path)
    assert [candidate.text for candidate in result] == ['final café\nsecond line']
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


@requires_ffmpeg
def test_webm_vhs_comment_wrapper_contains_execution_graph(tmp_path):
    path = tmp_path / 'clip.webm'
    wrapper = {'prompt': json.dumps(graph('workflow positive')),
               'workflow': {'nodes': []}}
    make_video(path, {'comment': json.dumps(wrapper)})
    result = read_generation_prompts(path)
    assert [candidate.text for candidate in result] == ['workflow positive']


@requires_ffmpeg
def test_video_workflow_sidecar_is_used_when_container_has_no_prompt(tmp_path):
    path = tmp_path / 'clip.mp4'
    make_video(path)
    sidecar = path.with_suffix('.json')
    sidecar.write_text(json.dumps(graph('sidecar positive')), encoding='utf-8')
    assert [item.text for item in read_generation_prompts(path)] == ['sidecar positive']


@requires_ffmpeg
def test_saved_sidecar_prompt_outranks_embedded_workflow(tmp_path):
    path = tmp_path / 'clip.mp4'
    make_video(path, {'prompt': json.dumps(graph('older workflow input'))})
    path.with_suffix('.json').write_text('{"positive_prompt":"saved positive"}', encoding='utf-8')
    assert [item.text for item in read_generation_prompts(path)] == ['saved positive']


@requires_ffmpeg
def test_video_without_metadata_or_sidecar_has_no_prompt(tmp_path):
    path = tmp_path / 'clip.mp4'
    make_video(path)
    assert read_generation_prompts(path) == []


def test_explicit_video_stream_tags_win_over_container_workflow(tmp_path, monkeypatch):
    path = tmp_path / 'clip.mp4'
    payload = {'format': {'tags': {'PROMPT': json.dumps(graph('workflow'))}},
               'streams': [
                   {'codec_type': 'audio', 'tags': {'positive_prompt': 'unrelated audio'}},
                   {'codec_type': 'video', 'tags': {'POSITIVE_PROMPT': 'saved video text'}},
               ]}
    monkeypatch.setattr(generation_prompt.subprocess, 'run', lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 0, json.dumps(payload), ''))
    assert [item.text for item in read_generation_prompts(path)] == ['saved video text']


def test_video_original_graph_is_used_when_compatibility_graph_is_missing(tmp_path, monkeypatch):
    payload = {'format': {'tags': {'prompt': '{}', 'prompt_original': json.dumps(graph())}}}
    monkeypatch.setattr(generation_prompt.subprocess, 'run', lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 0, json.dumps(payload), ''))
    assert [item.text for item in read_generation_prompts(tmp_path / 'clip.mp4')] == ['original input']


def test_sidecar_still_works_when_ffprobe_is_missing(tmp_path, monkeypatch):
    path = tmp_path / 'clip.mp4'
    path.with_suffix('.json').write_text(json.dumps(graph('sidecar')), encoding='utf-8')
    def missing(*args, **kwargs):
        raise FileNotFoundError('ffprobe')
    monkeypatch.setattr(generation_prompt.subprocess, 'run', missing)
    assert [item.text for item in read_generation_prompts(path)] == ['sidecar']
    path.with_suffix('.json').unlink()
    with pytest.raises(RuntimeError, match='FFprobe is not available'):
        read_generation_prompts(path)


def test_cancelled_request_does_not_start_ffprobe(tmp_path, monkeypatch):
    cancelled = Event()
    cancelled.set()
    def unexpected(*args, **kwargs):
        raise AssertionError('A cancelled request started a subprocess')
    monkeypatch.setattr(generation_prompt.subprocess, 'run', unexpected)
    assert read_generation_prompts(tmp_path / 'clip.mp4', cancelled) == []
