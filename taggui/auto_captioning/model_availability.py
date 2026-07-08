from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from huggingface_hub import scan_cache_dir
from huggingface_hub.constants import HUGGINGFACE_HUB_CACHE
from huggingface_hub.errors import CacheNotFound

MODEL_ARTIFACT_KIND_HUGGINGFACE = 'huggingface'
MODEL_ARTIFACT_KIND_REMOTE = 'remote'
MODEL_ARTIFACT_KIND_WD_TAGGER = 'wd_tagger'

_CACHE_INDEX: dict[str, dict[str, list[dict]]] = {}


@dataclass(frozen=True)
class ModelInstallState:
    status: str
    installed: bool
    source: str | None = None
    path: Path | None = None
    detail: str = ''


def clear_model_availability_cache():
    _CACHE_INDEX.clear()


def get_models_directory_target_path(models_directory_path: Path | None,
                                     model_id: str) -> Path | None:
    if models_directory_path is None:
        return None
    model_id_text = str(model_id or '').strip()
    if not model_id_text:
        return None
    model_path = Path(model_id_text)
    if model_path.is_absolute():
        return None
    return models_directory_path / model_path


def get_model_install_state(model_id: str,
                            models_directory_path: Path | None,
                            *,
                            artifact_kind: str,
                            revision: str | None = None) -> ModelInstallState:
    model_id_text = str(model_id or '').strip()
    if not model_id_text:
        return ModelInstallState(
            status='missing',
            installed=False,
            detail='No model selected.',
        )

    if artifact_kind == MODEL_ARTIFACT_KIND_REMOTE:
        return ModelInstallState(
            status='remote',
            installed=False,
            source='remote',
            detail='Remote API model.',
        )

    direct_path = Path(model_id_text).expanduser()
    if direct_path.is_dir():
        if is_model_directory_complete(direct_path, artifact_kind):
            return ModelInstallState(
                status='local',
                installed=True,
                source='local_path',
                path=direct_path,
                detail=f'Local model directory: {direct_path}',
            )
        return ModelInstallState(
            status='partial',
            installed=False,
            source='local_path',
            path=direct_path,
            detail=f'Local model directory looks incomplete: {direct_path}',
        )

    managed_path = get_models_directory_target_path(
        models_directory_path,
        model_id_text,
    )
    if managed_path is not None and managed_path.is_dir():
        if is_model_directory_complete(managed_path, artifact_kind):
            return ModelInstallState(
                status='cached',
                installed=True,
                source='models_directory',
                path=managed_path,
                detail=f'Cached in models directory: {managed_path}',
            )
        return ModelInstallState(
            status='partial',
            installed=False,
            source='models_directory',
            path=managed_path,
            detail=f'Partial model files in models directory: {managed_path}',
        )

    cached_snapshots = _get_cached_snapshot_paths(model_id_text, revision=revision)
    for snapshot_path in cached_snapshots:
        if is_model_directory_complete(snapshot_path, artifact_kind):
            return ModelInstallState(
                status='cached',
                installed=True,
                source='hf_cache',
                path=snapshot_path,
                detail=f'Cached in Hugging Face cache: {snapshot_path}',
            )
    if cached_snapshots:
        return ModelInstallState(
            status='partial',
            installed=False,
            source='hf_cache',
            path=cached_snapshots[0],
            detail='Partial model files found in Hugging Face cache.',
        )

    return ModelInstallState(
        status='missing',
        installed=False,
        detail='Model files are not cached locally yet.',
    )


def is_model_directory_complete(model_dir: Path, artifact_kind: str) -> bool:
    if not model_dir.is_dir():
        return False
    if artifact_kind == MODEL_ARTIFACT_KIND_WD_TAGGER:
        return ((model_dir / 'model.onnx').is_file()
                and (model_dir / 'selected_tags.csv').is_file())
    if not (model_dir / 'config.json').is_file():
        return False
    if not _has_complete_model_weights(model_dir):
        return False
    return _has_preprocessor_assets(model_dir)


def _has_complete_model_weights(model_dir: Path) -> bool:
    for index_name in (
        'model.safetensors.index.json',
        'pytorch_model.bin.index.json',
    ):
        index_path = model_dir / index_name
        if index_path.is_file():
            return _has_all_index_shards(index_path)

    for pattern in (
        '*.safetensors',
        '*.bin',
        '*.onnx',
        '*.gguf',
        '*.pt',
        '*.pth',
    ):
        if any(model_dir.rglob(pattern)):
            return True
    return False


def _has_all_index_shards(index_path: Path) -> bool:
    try:
        index_data = json.loads(index_path.read_text(encoding='utf-8'))
    except Exception:
        return False
    weight_map = index_data.get('weight_map')
    if not isinstance(weight_map, dict) or not weight_map:
        return False
    for relative_path in set(weight_map.values()):
        if not (index_path.parent / relative_path).is_file():
            return False
    return True


def _has_preprocessor_assets(model_dir: Path) -> bool:
    exact_files = (
        'processor_config.json',
        'preprocessor_config.json',
        'tokenizer.json',
        'tokenizer_config.json',
        'tokenizer.model',
        'vocab.json',
        'vocab.txt',
        'merges.txt',
        'special_tokens_map.json',
        'added_tokens.json',
    )
    for file_name in exact_files:
        if (model_dir / file_name).is_file():
            return True
    for pattern in (
        'image_processor*.json',
        'feature_extractor*.json',
        '*.model',
        '*.tiktoken',
    ):
        if any(model_dir.rglob(pattern)):
            return True
    return False


def _get_cached_snapshot_paths(repo_id: str,
                               *,
                               revision: str | None = None) -> list[Path]:
    cache_index = _get_hf_cache_index()
    repo_entries = cache_index.get(repo_id, [])
    if revision is None:
        return [entry['snapshot_path'] for entry in repo_entries]
    matched_paths = []
    for entry in repo_entries:
        if (entry['commit_hash'] == revision
                or revision in entry['refs']):
            matched_paths.append(entry['snapshot_path'])
    return matched_paths


def _get_hf_cache_index() -> dict[str, list[dict]]:
    cache_root = str(Path(HUGGINGFACE_HUB_CACHE))
    cached_index = _CACHE_INDEX.get(cache_root)
    if cached_index is not None:
        return cached_index

    try:
        cache_info = scan_cache_dir(cache_dir=cache_root)
    except (CacheNotFound, FileNotFoundError, OSError, ValueError):
        cache_index = {}
    else:
        cache_index: dict[str, list[dict]] = {}
        for repo in cache_info.repos:
            if repo.repo_type != 'model':
                continue
            repo_entries = cache_index.setdefault(repo.repo_id, [])
            for revision in repo.revisions:
                repo_entries.append({
                    'commit_hash': revision.commit_hash,
                    'refs': frozenset(revision.refs),
                    'snapshot_path': revision.snapshot_path,
                    'last_modified': revision.last_modified,
                })
        for repo_entries in cache_index.values():
            repo_entries.sort(
                key=lambda entry: entry['last_modified'],
                reverse=True,
            )

    _CACHE_INDEX[cache_root] = cache_index
    return cache_index
