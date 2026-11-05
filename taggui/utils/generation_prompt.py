"""Read positive prompts from image and video metadata on demand.

ComfyUI stores an execution graph in ``prompt`` and often a separate editor
graph in ``workflow``. Neither graph records arbitrary custom-node outputs.
This module only follows recognizable positive-conditioning and text inputs;
it never executes a workflow or writes to a media file, sidecar, or database.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import re
import subprocess
import sys

from PIL import Image

from utils.sidecar import is_taggui_metadata_dict


@dataclass(frozen=True)
class PromptCandidate:
    text: str
    label: str
    note: str = ''
    verified: bool = True


_SIMPLE_PROMPT_TYPES = {'SimplePromptStandalone', 'PgPromptSimple'}
_ORIGINAL_SIMPLE_NOTE = (
    'Original Simple Prompt input. Comments and random choices may have been '
    'processed during generation; the resulting text is not saved by this node.'
)
_UNVERIFIED_NOTE = (
    'Found in the workflow, but its connection to the generated file '
    'could not be verified.'
)
_CUSTOM_NOTE = (
    'Text traced through a custom node. Its output may have been changed '
    'during generation.'
)
_SWITCH_NOTE = 'The active switch branch could not be determined from the saved metadata.'
_INCOMPLETE_NOTE = 'Some positive workflow branches could not be read.'
_VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.webm'}


def _json_object(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, bytes):
        try:
            value = value.decode('utf-8-sig')
        except UnicodeError:
            return None
    if not isinstance(value, str):
        return None
    try:
        result = json.loads(value)
    except (ValueError, TypeError, RecursionError):
        return None
    return result if isinstance(result, dict) else None


def _is_api_graph(value):
    return isinstance(value, dict) and any(
        isinstance(node, dict) and isinstance(node.get('class_type'), str)
        and isinstance(node.get('inputs'), dict)
        for node in value.values()
    )


def _is_workflow(value):
    return isinstance(value, dict) and isinstance(value.get('nodes'), list)


def _decode_exif_text(value):
    if isinstance(value, str):
        return value.rstrip('\x00')
    if not isinstance(value, bytes):
        return ''
    if value.startswith(b'UNICODE\x00'):
        data = value[8:]
        try:
            if data.startswith((b'\xfe\xff', b'\xff\xfe')):
                return data.decode('utf-16').rstrip('\x00')
            # EXIF UserComment is commonly BOM-less UTF-16BE; some writers use
            # LE instead. ASCII-heavy text exposes the byte order via zeros.
            even_zeros = data[0::2].count(0)
            odd_zeros = data[1::2].count(0)
            encoding = 'utf-16-le' if odd_zeros > even_zeros else 'utf-16-be'
            return data.decode(encoding).rstrip('\x00')
        except UnicodeError:
            return data.decode('utf-16-be', errors='replace').rstrip('\x00')
    if value.startswith((b'ASCII\x00\x00\x00', b'\x00' * 8)):
        value = value[8:]
    return value.decode('utf-8', errors='replace').rstrip('\x00')


def _read_metadata(path):
    with Image.open(path) as image:
        metadata = dict(image.info)
        try:
            exif = image.getexif()
            # ComfyUI stores extra metadata in successive EXIF tags, so the
            # tag number of a named prompt depends on the other fields saved.
            values = list(exif.values())
            try:
                values.append(exif.get_ifd(0x8769).get(0x9286))
            except (AttributeError, KeyError, TypeError, ValueError):
                pass
        except (AttributeError, OSError, ValueError, SyntaxError):
            values = []
        for value in values:
            text = _decode_exif_text(value)
            if not text:
                continue
            # ComfyUI WebP writes separate EXIF records as ``name:JSON``.
            pattern = (r'(?:^|\n)(prompt|workflow|parameters|positiveprompt(?:_\w+)?|'
                       r'positive_prompt|positive prompt|positive|umi_prompt|'
                       r'invokeai_metadata|sui_image_params):\s*')
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                try:
                    data, _ = json.JSONDecoder().raw_decode(text[match.end():])
                except (ValueError, RecursionError):
                    continue
                key = match.group(1)
                metadata.setdefault(key.lower() if key.lower() in ('prompt', 'workflow', 'parameters') else key, data)
            wrapper = _json_object(text)
            if wrapper:
                for key, value in wrapper.items():
                    normalized = re.sub(r'[^a-z0-9]', '', str(key).lower())
                    if (normalized in {'prompt', 'workflow', 'parameters', 'positive',
                                       'positiveprompt', 'negativeprompt', 'umiprompt',
                                       'invokeaimetadata', 'comment', 'suiimageparams'}
                            or str(key).lower().startswith('positiveprompt_')):
                        metadata.setdefault(key, value)
            if 'parameters' not in metadata and re.search(
                r'(?im)^Negative prompt:\s*|^Steps:\s*\d', text
            ):
                metadata['parameters'] = text
    return metadata


def _read_video_metadata(path):
    """Read container and video-stream tags without decoding video frames."""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries',
             'format_tags:stream=codec_type:stream_tags', '-of', 'json', '--', str(path)],
            capture_output=True, encoding='utf-8', errors='replace', timeout=15,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) if sys.platform == 'win32' else 0,
        )
    except FileNotFoundError as error:
        raise RuntimeError('FFprobe is not available. Install FFmpeg and add it to PATH.') from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError('Timed out while reading video metadata.') from error
    if result.returncode:
        raise RuntimeError(f'FFprobe could not read the video: {result.stderr.strip() or "unknown error"}')
    try:
        probe = json.loads(result.stdout)
    except (ValueError, RecursionError) as error:
        raise RuntimeError('FFprobe returned invalid video metadata.') from error
    if not isinstance(probe, dict):
        raise RuntimeError('FFprobe returned invalid video metadata.')

    sources = []

    def add_source(tags):
        if not isinstance(tags, dict):
            return
        # MP4 preserves tag case, while WebM commonly exposes uppercase tags.
        tags = {str(key).lower(): value for key, value in tags.items()}
        sources.append(tags)
        for key in ('comment', 'description', 'user_data'):
            value = tags.get(key)
            data = _json_object(value)
            if _is_api_graph(data):
                sources.append({'prompt': data})
            elif _is_workflow(data):
                sources.append({'workflow': data})
            elif isinstance(data, dict):
                sources.append({str(name).lower(): item for name, item in data.items()})
            elif isinstance(value, str) and re.search(
                r'(?im)^Negative prompt:\s*|^Steps:\s*\d', value
            ):
                sources.append({'parameters': value})

    container = probe.get('format')
    if isinstance(container, dict):
        add_source(container.get('tags'))
    for stream in probe.get('streams', []):
        if isinstance(stream, dict) and stream.get('codec_type') == 'video':
            add_source(stream.get('tags'))
    return sources


def _workflow_graph(workflow):
    """Translate the common editor graph shapes to the execution-graph shape."""
    nodes = {}
    original_nodes = {}
    for node in workflow.get('nodes', []):
        if not isinstance(node, dict) or node.get('mode', 0) != 0:
            continue
        node_id = str(node.get('id', ''))
        if not node_id:
            continue
        kind = node.get('type', '')
        inputs = {}
        widgets = node.get('widgets_values', [])
        if isinstance(widgets, dict):
            inputs.update(widgets)
        elif isinstance(widgets, list):
            if kind in _SIMPLE_PROMPT_TYPES:
                names = ('positive', 'negative')
            elif kind == 'CLIPTextEncodeSDXL':
                names = ('width', 'height', 'crop_w', 'crop_h', 'target_width',
                         'target_height', 'text_g', 'text_l')
            elif kind in ('CLIPTextEncode', 'CLIPTextEncodeSDXLRefiner'):
                names = ('text',) if kind == 'CLIPTextEncode' else (
                    'ascore', 'width', 'height', 'text')
            elif kind in ('easy anythingIndexSwitch', 'easy textIndexSwitch',
                          'easy conditioningIndexSwitch'):
                names = ('index',)
            elif kind in ('easy int', 'PrimitiveInt', 'PrimitiveStringMultiline', 'easy string'):
                names = ('value',)
            else:
                names = ()
            inputs.update({name: value for name, value in zip(names, widgets)})
        nodes[node_id] = {'class_type': kind, 'inputs': inputs,
                          '_meta': {'title': node.get('title') or kind}}
        original_nodes[node_id] = node

    for link in workflow.get('links', []):
        if not isinstance(link, (list, tuple)) or len(link) < 5:
            continue
        _, source, source_slot, target, target_slot = link[:5]
        source_id, target_id = str(source), str(target)
        target_node = original_nodes.get(target_id)
        if source_id not in nodes or target_id not in nodes or not target_node:
            continue
        node_inputs = target_node.get('inputs', [])
        if not isinstance(node_inputs, list) or not isinstance(target_slot, int):
            continue
        if 0 <= target_slot < len(node_inputs) and isinstance(node_inputs[target_slot], dict):
            name = node_inputs[target_slot].get('name')
            if isinstance(name, str):
                nodes[target_id]['inputs'][name] = [source_id, source_slot]
    return nodes


def _graph_candidates(graph):
    graph = {str(key): value for key, value in graph.items() if isinstance(value, dict)}
    candidates = []

    def constant_int(value):
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if (isinstance(value, (list, tuple)) and len(value) == 2
                and value[1] == 0):
            node = graph.get(str(value[0]), {})
            if node.get('class_type') in ('easy int', 'PrimitiveInt'):
                inputs = node.get('inputs', {})
                number = inputs.get('value') if isinstance(inputs, dict) else None
                if isinstance(number, int) and not isinstance(number, bool):
                    return number
        return None

    def follow(value, seen, note='', verified=True):
        if isinstance(value, str):
            return []  # Literals are emitted by their owning input, not as links.
        if (not isinstance(value, (list, tuple)) or len(value) != 2
                or not isinstance(value[1], int)):
            return []
        node_id, output = str(value[0]), value[1]
        if node_id in seen or len(seen) >= 100 or node_id not in graph:
            return []
        node = graph[node_id]
        inputs = node.get('inputs')
        if not isinstance(inputs, dict):
            return []
        kind = str(node.get('class_type', ''))
        meta = node.get('_meta') if isinstance(node.get('_meta'), dict) else {}
        title = str(meta.get('title') or kind or 'Node')
        seen = seen | {node_id}

        if kind in _SIMPLE_PROMPT_TYPES:
            if output != 0:
                return []
            fields = ('positive',)
            note = ' '.join(filter(None, (note, _ORIGINAL_SIMPLE_NOTE)))
        elif kind in ('easy anythingIndexSwitch', 'easy textIndexSwitch',
                      'easy conditioningIndexSwitch'):
            prefix = {'easy anythingIndexSwitch': 'value', 'easy textIndexSwitch': 'text',
                      'easy conditioningIndexSwitch': 'cond'}[kind]
            index = constant_int(inputs.get('index'))
            if index is not None:
                fields = (f'{prefix}{index}',)
            else:
                fields = tuple(key for key in inputs if re.fullmatch(prefix + r'\d+', key))
                note = ' '.join(filter(None, (note, _SWITCH_NOTE)))
                verified = False
        elif kind == 'SavePositivePromptSG':
            fields = ('text',)
        elif 'CLIPTextEncode' in kind or 'TextEncode' in kind:
            # Dual encoders such as TextEncodeFibo2 return positive on output 0
            # and negative on output 1. Do not label the latter as positive.
            if output != 0 and any('negative' in str(key).lower() for key in inputs):
                return []
            fields = ('text', 'text_g', 'text_l', 'clip_l', 't5xxl', 'prompt')
        elif kind == 'SDXLPromptStyler':
            if output != 0:
                return []
            fields = ('text_positive', 'positive', 'positive_prompt')
        else:
            if kind == 'ControlNetApplyAdvanced' and output != 0:
                return []
            fields = tuple(key for key in inputs if (
                key.lower() in {'positive', 'positive_prompt', 'text', 'prompt',
                                'conditioning', 'conditioning_to', 'conditioning_from',
                                'conditioning_1', 'conditioning_2', 'string', 'value'}
                and 'negative' not in key.lower()
            ))
            if fields and kind not in {'ConditioningCombine', 'ConditioningAverage',
                                       'ConditioningSetArea', 'ConditioningSetMask',
                                       'ControlNetApplyAdvanced', 'Reroute',
                                       'PrimitiveStringMultiline', 'easy string'}:
                note = note or _CUSTOM_NOTE
                verified = False

        found = []
        for field in fields:
            item = inputs.get(field)
            if isinstance(item, str) and item.strip():
                found.append(PromptCandidate(item.strip(), f'{title} #{node_id} · {field}',
                                             note, verified))
            else:
                found.extend(follow(item, seen, note, verified))
        return found

    incomplete = False
    for node_id, node in graph.items():
        inputs = node.get('inputs')
        if not isinstance(inputs, dict):
            continue
        kind = str(node.get('class_type', ''))
        if kind in _SIMPLE_PROMPT_TYPES:
            continue
        kind_lower = kind.lower()
        anchor = 'sampler' in kind_lower or 'guider' in kind_lower
        if not anchor:
            continue
        for field in ('positive', 'conditioning'):
            if field not in inputs:
                continue
            value = inputs.get(field)
            if isinstance(value, str) and value.strip():
                candidates.append(PromptCandidate(value.strip(), f'{kind} #{node_id} · {field}'))
            else:
                found = follow(value, {node_id})
                candidates.extend(found)
                if value and not found:
                    incomplete = True

    if candidates and incomplete:
        candidates = [replace(item, note=' '.join(filter(None, (item.note, _INCOMPLETE_NOTE))),
                              verified=False) for item in candidates]

    if not candidates:
        # A workflow can contain no recognizable sampler, e.g. a custom video
        # pipeline. Show known prompt fields, but don't assert they were used.
        for node_id, node in graph.items():
            kind = str(node.get('class_type', ''))
            if kind in _SIMPLE_PROMPT_TYPES:
                for item in follow([node_id, 0], set()):
                    candidates.append(PromptCandidate(item.text, item.label,
                                                      f'{_UNVERIFIED_NOTE} {item.note}', False))
    return candidates


def _unique(candidates):
    result, seen = [], set()
    for candidate in candidates:
        if candidate.text not in seen:
            result.append(candidate)
            seen.add(candidate.text)
    return result


def _metadata_prompt_candidates(metadata, *, source='', depth=0, skip_root_prompt=False):
    """Collect explicit text fields from recognized metadata containers."""
    if depth > 3 or not isinstance(metadata, dict):
        return []
    saved = []
    for key, value in metadata.items():
        name = str(key)
        normalized = re.sub(r'[^a-z0-9]', '', name.lower())
        label = f'{source} · {name}' if source else name
        is_sg_prompt = name.lower().startswith('positiveprompt_')
        if skip_root_prompt and depth == 0 and normalized == 'prompt':
            continue

        if is_sg_prompt or normalized in {'positive', 'positiveprompt', 'umiprompt'}:
            if not isinstance(value, str):
                continue
            text = value
            if is_sg_prompt:
                # ComfyUI serializes this node's extra_pnginfo value as JSON.
                try:
                    decoded = json.loads(value)
                except (ValueError, RecursionError):
                    decoded = value
                if isinstance(decoded, str):
                    text = decoded
            if text.strip():
                saved.append(PromptCandidate(text.strip(), f'Saved positive prompt · {label}'))
            continue

        if normalized in {'parameters', 'invokeaimetadata', 'comment', 'suiimageparams'}:
            data = _json_object(value)
            if data is not None:
                saved.extend(_metadata_prompt_candidates(data, source=label, depth=depth + 1))
            elif normalized == 'parameters' and isinstance(value, str) and value.strip():
                # A1111/Forge parameters contain positive text followed by
                # negative text and sampling settings. Never copy JSON arrays.
                try:
                    decoded = json.loads(value)
                except (ValueError, RecursionError):
                    decoded = None
                if not isinstance(decoded, (dict, list)):
                    positive = re.split(r'(?im)^Negative prompt:\s*|^Steps:\s*\d',
                                        value, maxsplit=1)[0].strip()
                    if positive:
                        saved.append(PromptCandidate(positive, f'Saved generation parameters · {label}'))
            continue

        if normalized == 'prompt' and isinstance(value, str) and value.strip():
            # ComfyUI's prompt key normally holds a JSON execution graph;
            # other generators use the same key for literal positive text.
            try:
                decoded = json.loads(value)
            except (ValueError, RecursionError):
                decoded = None
            if not isinstance(decoded, (dict, list)):
                positive = re.split(r'(?im)^Negative prompt:\s*|^Steps:\s*\d',
                                    value, maxsplit=1)[0].strip()
                if positive:
                    saved.append(PromptCandidate(positive, f'Saved prompt · {label}'))
    return saved


def _from_metadata(metadata):
    # Check explicitly labeled fields and known metadata containers before
    # decoding a potentially very large execution graph in the prompt field.
    saved = _unique(_metadata_prompt_candidates(metadata, skip_root_prompt=True))
    if saved:
        return saved

    api_graph = _json_object(metadata.get('prompt'))
    if api_graph is not None:
        # Avoid decoding a potentially large ComfyUI graph twice.
        metadata = dict(metadata)
        metadata['prompt'] = api_graph
    saved = _unique(_metadata_prompt_candidates(metadata))
    if saved:
        return saved

    workflow = _json_object(metadata.get('workflow'))
    if _is_api_graph(api_graph):
        found = _unique(_graph_candidates(api_graph))
        if found:
            return found
    original_graph = _json_object(metadata.get('prompt_original'))
    if _is_api_graph(original_graph):
        found = _unique(_graph_candidates(original_graph))
        if found:
            return found
    if _is_workflow(workflow):
        return _unique(_graph_candidates(_workflow_graph(workflow)))
    return []


def _sidecar_metadata(path):
    """Read only a foreign sibling JSON, preserving TagGUI-owned sidecars."""
    sidecar = path.with_suffix('.json')
    try:
        with sidecar.open('r', encoding='utf-8-sig') as handle:
            payload = json.load(handle)
    except (OSError, ValueError, UnicodeError, RecursionError):
        return None
    if isinstance(payload, dict) and not is_taggui_metadata_dict(payload):
        if _is_api_graph(payload):
            return {'prompt': payload}
        if _is_workflow(payload):
            return {'workflow': payload}
        return payload
    return None


def read_generation_prompts(path, cancelled=None):
    """Return candidates for one media file, optionally reading a workflow sidecar."""
    path = Path(path)
    if cancelled is not None and cancelled.is_set():
        return []
    probe_error = None
    if path.suffix.lower() in _VIDEO_EXTENSIONS:
        try:
            sources = _read_video_metadata(path)
        except RuntimeError as error:
            sources = []
            probe_error = error
    else:
        sources = [_read_metadata(path)]
    if cancelled is not None and cancelled.is_set():
        return []
    # Explicit text in a container or video stream outranks workflow graphs.
    saved = _unique([candidate for metadata in sources
                     for candidate in _metadata_prompt_candidates(metadata, skip_root_prompt=True)])
    if saved:
        return saved

    prepared = []
    for metadata in sources:
        graph = _json_object(metadata.get('prompt'))
        if graph is not None:
            metadata = dict(metadata)
            metadata['prompt'] = graph
        prepared.append(metadata)
    # Literal prompt fields also outrank graphs in other metadata sources.
    saved = _unique([candidate for metadata in prepared
                     for candidate in _metadata_prompt_candidates(metadata)])
    if saved:
        return saved

    sidecar = _sidecar_metadata(path)
    if sidecar is not None:
        saved = _unique(_metadata_prompt_candidates(sidecar))
        if saved:
            return saved
    if cancelled is not None and cancelled.is_set():
        return []
    found = _unique([candidate for metadata in prepared for candidate in _from_metadata(metadata)])
    if found:
        return found
    if sidecar is not None:
        found = _from_metadata(sidecar)
        if found:
            return found
    if probe_error is not None:
        raise probe_error
    return []
