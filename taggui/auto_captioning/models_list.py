"""Lightweight auto-captioning model registry.

Keep model metadata importable by the GUI without importing torch,
transformers, torchvision, or every model adapter during application startup.
Concrete model classes are resolved only when captioning actually starts.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path

from auto_captioning.model_availability import (
    MODEL_ARTIFACT_KIND_HUGGINGFACE,
    MODEL_ARTIFACT_KIND_REMOTE,
    MODEL_ARTIFACT_KIND_WD_TAGGER,
)

MODEL_KIND_LOCAL = 'local'
MODEL_KIND_REMOTE = 'remote'
MODEL_KIND_WD_TAGGER = 'wd_tagger'

MODELS = [
    # Qwen VL — native video + image captioning (requires qwen-vl-utils)
    'Qwen/Qwen2.5-VL-3B-Instruct',
    'Qwen/Qwen2.5-VL-7B-Instruct',
    'Qwen/Qwen3.5-4B',
    'Qwen/Qwen3.5-9B',
    'huihui-ai/Huihui-Qwen3.5-9B-abliterated',
    'google/gemma-4-E2B-it',
    'google/gemma-4-E4B-it',
    'google/gemma-4-26B-A4B-it',
    'google/gemma-4-31B-it',
    'fancyfeast/llama-joycaption-beta-one-hf-llava',
    'THUDM/cogvlm-chat-hf',
    'THUDM/cogvlm2-llama3-chat-19B-int4',
    'THUDM/cogvlm2-llama3-chat-19B',
    'microsoft/Florence-2-large-ft',
    'microsoft/Florence-2-large',
    'microsoft/Florence-2-base-ft',
    'microsoft/Florence-2-base',
    'MiaoshouAI/Florence-2-large-PromptGen-v2.0',
    'MiaoshouAI/Florence-2-base-PromptGen-v2.0',
    'microsoft/Phi-3-vision-128k-instruct',
    'llava-hf/llava-v1.6-mistral-7b-hf',
    'llava-hf/llava-v1.6-vicuna-7b-hf',
    'llava-hf/llava-v1.6-vicuna-13b-hf',
    'llava-hf/llava-v1.6-34b-hf',
    'xtuner/llava-llama-3-8b-v1_1-transformers',
    'vikhyatk/moondream2',
    'vikhyatk/moondream1',
    'SmilingWolf/wd-eva02-large-tagger-v3',
    'SmilingWolf/wd-vit-large-tagger-v3',
    'SmilingWolf/wd-swinv2-tagger-v3',
    'SmilingWolf/wd-convnext-tagger-v3',
    'SmilingWolf/wd-vit-tagger-v3',
    'SmilingWolf/wd-v1-4-moat-tagger-v2',
    'SmilingWolf/wd-v1-4-swinv2-tagger-v2',
    'SmilingWolf/wd-v1-4-convnext-tagger-v2',
    'SmilingWolf/wd-v1-4-convnextv2-tagger-v2',
    'SmilingWolf/wd-v1-4-vit-tagger-v2',
    'llava-hf/llava-1.5-7b-hf',
    'llava-hf/llava-1.5-13b-hf',
    'llava-hf/bakLlava-v1-hf',
    'Salesforce/instructblip-vicuna-7b',
    'Salesforce/instructblip-vicuna-13b',
    'Salesforce/instructblip-flan-t5-xl',
    'Salesforce/instructblip-flan-t5-xxl',
    'Salesforce/blip2-opt-2.7b',
    'Salesforce/blip2-opt-6.7b',
    'Salesforce/blip2-opt-6.7b-coco',
    'Salesforce/blip2-flan-t5-xl',
    'Salesforce/blip2-flan-t5-xxl',
    'microsoft/kosmos-2-patch14-224',
    'Remote',
]

if find_spec('gptqmodel') is not None:
    MODELS.extend([
        'internlm/internlm-xcomposer2-vl-7b-4bit',
        'internlm/internlm-xcomposer2-vl-7b',
        'internlm/internlm-xcomposer2-vl-1_8b',
        'internlm/internlm-xcomposer2-4khd-7b',
    ])


def get_model_kind(model_id: str) -> str:
    """Classify a model without importing its implementation."""
    model_id_text = str(model_id or '').strip()
    model_path = Path(model_id_text).expanduser()
    if (
        model_path.is_dir()
        and (model_path / 'model.onnx').is_file()
        and (model_path / 'selected_tags.csv').is_file()
    ):
        return MODEL_KIND_WD_TAGGER

    lowercase_model_id = model_id_text.lower()
    if 'wd' in lowercase_model_id and 'tagger' in lowercase_model_id:
        return MODEL_KIND_WD_TAGGER
    if 'remote' in lowercase_model_id:
        return MODEL_KIND_REMOTE
    return MODEL_KIND_LOCAL


def get_model_artifact_kind(model_id: str) -> str:
    model_kind = get_model_kind(model_id)
    if model_kind == MODEL_KIND_WD_TAGGER:
        return MODEL_ARTIFACT_KIND_WD_TAGGER
    if model_kind == MODEL_KIND_REMOTE:
        return MODEL_ARTIFACT_KIND_REMOTE
    return MODEL_ARTIFACT_KIND_HUGGINGFACE


def get_model_download_revision(model_id: str) -> str | None:
    """Return download-only metadata without importing the model adapter."""
    if 'moondream2' in str(model_id or '').lower():
        return '2024-08-26'
    return None


def _load_model_class(module_name: str, class_name: str):
    return getattr(import_module(module_name), class_name)


@lru_cache(maxsize=None)
def get_model_class(model_id: str):
    """Resolve a concrete model class on first use."""
    lowercase_model_id = str(model_id or '').lower()

    module_name = 'auto_captioning.auto_captioning_model'
    class_name = 'AutoCaptioningModel'
    if 'qwen2.5-vl' in lowercase_model_id or 'qwen3.5' in lowercase_model_id:
        module_name, class_name = 'auto_captioning.models.qwen_vl', 'QwenVL'
    elif 'gemma-4' in lowercase_model_id:
        module_name, class_name = 'auto_captioning.models.gemma_4', 'Gemma4'
    elif 'cogvlm2' in lowercase_model_id:
        module_name, class_name = 'auto_captioning.models.cogvlm2', 'Cogvlm2'
    elif 'cogvlm' in lowercase_model_id:
        module_name, class_name = 'auto_captioning.models.cogvlm', 'Cogvlm'
    elif 'florence' in lowercase_model_id:
        module_name = 'auto_captioning.models.florence_2'
        class_name = (
            'Florence2Promptgen'
            if 'promptgen' in lowercase_model_id
            else 'Florence2'
        )
    elif 'joycaption' in lowercase_model_id:
        module_name, class_name = 'auto_captioning.models.joycaption', 'Joycaption'
    elif 'kosmos' in lowercase_model_id:
        module_name, class_name = 'auto_captioning.models.kosmos_2', 'Kosmos2'
    elif 'llava-v1.6-34b' in lowercase_model_id:
        module_name, class_name = 'auto_captioning.models.llava_next', 'LlavaNext34b'
    elif 'llava-v1.6-mistral' in lowercase_model_id:
        module_name, class_name = 'auto_captioning.models.llava_next', 'LlavaNextMistral'
    elif 'llava-v1.6-vicuna' in lowercase_model_id:
        module_name, class_name = 'auto_captioning.models.llava_next', 'LlavaNextVicuna'
    elif 'llava-llama-3' in lowercase_model_id:
        module_name, class_name = 'auto_captioning.models.llava_llama_3', 'LlavaLlama3'
    elif 'llava' in lowercase_model_id:
        module_name, class_name = 'auto_captioning.models.llava_1_point_5', 'Llava1Point5'
    elif 'moondream1' in lowercase_model_id:
        module_name, class_name = 'auto_captioning.models.moondream', 'Moondream1'
    elif 'moondream2' in lowercase_model_id:
        module_name, class_name = 'auto_captioning.models.moondream', 'Moondream2'
    elif 'phi-3' in lowercase_model_id:
        module_name, class_name = 'auto_captioning.models.phi_3_vision', 'Phi3Vision'
    elif get_model_kind(model_id) == MODEL_KIND_WD_TAGGER:
        module_name, class_name = 'auto_captioning.models.wd_tagger', 'WdTagger'
    elif 'xcomposer2' in lowercase_model_id:
        module_name = 'auto_captioning.models.xcomposer2'
        class_name = 'Xcomposer2_4khd' if '4khd' in lowercase_model_id else 'Xcomposer2'
    elif get_model_kind(model_id) == MODEL_KIND_REMOTE:
        module_name, class_name = 'auto_captioning.models.remote', 'RemoteGen'

    return _load_model_class(module_name, class_name)
