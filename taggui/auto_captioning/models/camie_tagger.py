from __future__ import annotations

import json
from pathlib import Path

import huggingface_hub
import numpy as np
from PIL import Image as PilImage

try:
    import onnxruntime as ort
    _ONNXRUNTIME_IMPORT_ERROR = None
except Exception as exc:
    ort = None
    _ONNXRUNTIME_IMPORT_ERROR = exc

from auto_captioning.model_availability import (
    CAMIE_TAGGER_MODEL_ID,
    CAMIE_TAGGER_REVISION,
    MODEL_ARTIFACT_KIND_CAMIE_TAGGER,
)
from auto_captioning.models.wd_tagger import (
    KAOMOJIS,
    WdTagger,
    get_tags_to_exclude,
)
from utils.image import Image


MODEL_FILENAME = 'camie-tagger-v2.onnx'
METADATA_FILENAME = 'camie-tagger-v2-metadata.json'
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
PADDING_COLOR = (124, 116, 104)
EXCLUDED_CATEGORIES = frozenset({'rating'})


def _resolve_model_asset(model_id: str, filename: str) -> Path:
    local_path = Path(model_id).expanduser() / filename
    if local_path.is_file():
        return local_path
    revision = (
        CAMIE_TAGGER_REVISION
        if str(model_id).casefold() == CAMIE_TAGGER_MODEL_ID.casefold()
        else None
    )
    return Path(huggingface_hub.hf_hub_download(
        repo_id=model_id,
        filename=filename,
        revision=revision,
    ))


def _normalize_tag(tag: str) -> str:
    if tag in KAOMOJIS:
        return tag
    return tag.replace('_', ' ')


def preprocess_camie_image(
        pil_image: PilImage.Image,
        image_size: int) -> np.ndarray:
    if image_size <= 0:
        raise ValueError('Camie Tagger image size must be positive.')

    pil_image = pil_image.convert('RGB')
    width, height = pil_image.size
    if width <= 0 or height <= 0:
        raise ValueError('Camie Tagger cannot process an empty image.')

    if width >= height:
        resized_width = image_size
        resized_height = max(1, int(image_size * height / width))
    else:
        resized_height = image_size
        resized_width = max(1, int(image_size * width / height))

    if pil_image.size != (resized_width, resized_height):
        pil_image = pil_image.resize(
            (resized_width, resized_height),
            resample=PilImage.Resampling.LANCZOS,
        )

    canvas = PilImage.new(
        'RGB',
        (image_size, image_size),
        PADDING_COLOR,
    )
    canvas.paste(
        pil_image,
        (
            (image_size - resized_width) // 2,
            (image_size - resized_height) // 2,
        ),
    )

    image_array = np.asarray(canvas, dtype=np.float32) / 255.0
    image_array = (image_array - IMAGENET_MEAN) / IMAGENET_STD
    image_array = np.transpose(image_array, (2, 0, 1))
    return np.ascontiguousarray(image_array[None, ...], dtype=np.float32)


class CamieTaggerModel:
    def __init__(
            self,
            model_id: str,
            *,
            use_gpu: bool = True,
            gpu_index: int = 0):
        if ort is None:
            raise RuntimeError(
                'onnxruntime is not available. '
                f'Original import error: {_ONNXRUNTIME_IMPORT_ERROR}'
            )

        metadata_path = _resolve_model_asset(model_id, METADATA_FILENAME)
        model_path = _resolve_model_asset(model_id, MODEL_FILENAME)
        self.tags, self.categories, metadata_image_size = (
            self._load_metadata(metadata_path)
        )

        available_providers = set(ort.get_available_providers())
        providers = [
            (
                'CUDAExecutionProvider',
                {'device_id': max(0, int(gpu_index))},
            )
        ] if (
            use_gpu and 'CUDAExecutionProvider' in available_providers
        ) else []
        if 'CPUExecutionProvider' in available_providers:
            providers.append('CPUExecutionProvider')
        session_options = ort.SessionOptions()
        session_options.log_severity_level = 3
        session_arguments = {'sess_options': session_options}
        if providers:
            session_arguments['providers'] = providers
        self.inference_session = ort.InferenceSession(
            str(model_path),
            **session_arguments,
        )

        inputs = self.inference_session.get_inputs()
        if len(inputs) != 1:
            raise RuntimeError(
                'Camie Tagger v2 must expose exactly one image input.'
            )
        self.input_name = inputs[0].name
        self.image_size = self._resolve_image_size(
            inputs[0].shape,
            metadata_image_size,
        )

        outputs = self.inference_session.get_outputs()
        if not outputs:
            raise RuntimeError('Camie Tagger v2 exposes no ONNX outputs.')
        output_names = [
            getattr(output, 'name', '') or ''
            for output in outputs
        ]
        self.refined_output_index = None
        if 'refined_predictions' in output_names:
            self.refined_output_name = 'refined_predictions'
            refined_output_index = output_names.index(
                self.refined_output_name
            )
        elif any(output_names):
            raise RuntimeError(
                'Camie Tagger v2 does not expose the required '
                f'`refined_predictions` output. Found: {output_names}.'
            )
        else:
            self.refined_output_name = None
            self.refined_output_index = 1 if len(outputs) >= 2 else 0
            refined_output_index = self.refined_output_index

        refined_output = outputs[refined_output_index]
        output_shape = refined_output.shape
        if (len(output_shape) >= 2
                and isinstance(output_shape[-1], int)
                and output_shape[-1] != len(self.tags)):
            raise RuntimeError(
                'Camie Tagger metadata contains '
                f'{len(self.tags)} tags, but the ONNX output contains '
                f'{output_shape[-1]}.'
            )

    @staticmethod
    def _load_metadata(
            metadata_path: Path) -> tuple[list[str], list[str], int]:
        try:
            with open(metadata_path, 'r', encoding='utf-8') as metadata_file:
                metadata = json.load(metadata_file)
            dataset_info = metadata['dataset_info']
            tag_mapping = dataset_info['tag_mapping']
            idx_to_tag = tag_mapping['idx_to_tag']
            tag_to_category = tag_mapping['tag_to_category']
            total_tags = int(dataset_info['total_tags'])
            image_size = int(metadata['model_info']['img_size'])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(
                f'Invalid Camie Tagger metadata in {metadata_path}: {exc}'
            ) from exc

        if total_tags <= 0 or image_size <= 0:
            raise ValueError(
                'Invalid Camie Tagger metadata: tag count and image size '
                'must be positive.'
            )
        if not isinstance(idx_to_tag, dict):
            raise ValueError(
                'Invalid Camie Tagger metadata: idx_to_tag must be an object.'
            )
        if not isinstance(tag_to_category, dict):
            raise ValueError(
                'Invalid Camie Tagger metadata: tag_to_category must be an '
                'object.'
            )

        tags = []
        categories = []
        for index in range(total_tags):
            raw_tag = idx_to_tag.get(str(index))
            if not isinstance(raw_tag, str) or not raw_tag:
                raise ValueError(
                    'Invalid Camie Tagger metadata: '
                    f'missing tag for output index {index}.'
                )
            category = tag_to_category.get(raw_tag)
            if not isinstance(category, str) or not category:
                raise ValueError(
                    'Invalid Camie Tagger metadata: '
                    f'missing category for tag {raw_tag!r}.'
                )
            tags.append(_normalize_tag(raw_tag))
            categories.append(category.casefold())

        return tags, categories, image_size

    @staticmethod
    def _resolve_image_size(
            input_shape: list | tuple,
            metadata_image_size: int) -> int:
        if len(input_shape) != 4:
            raise RuntimeError(
                'Camie Tagger v2 expects a four-dimensional NCHW input.'
            )
        channel_count = input_shape[1]
        if isinstance(channel_count, int) and channel_count != 3:
            raise RuntimeError(
                'Camie Tagger v2 expects a three-channel RGB input.'
            )

        input_height, input_width = input_shape[-2:]
        if isinstance(input_height, int) and isinstance(input_width, int):
            if input_height != input_width:
                raise RuntimeError(
                    'Camie Tagger v2 expects a square image input.'
                )
            if input_height != metadata_image_size:
                raise RuntimeError(
                    'Camie Tagger metadata and ONNX input dimensions disagree: '
                    f'{metadata_image_size} versus {input_height}.'
                )
            return input_height
        if metadata_image_size <= 0:
            raise ValueError(
                'Camie Tagger metadata contains an invalid image size.'
            )
        return metadata_image_size

    def generate_tags(
            self,
            image_array: np.ndarray,
            wd_tagger_settings: dict) -> tuple[tuple, tuple]:
        if self.refined_output_name is not None:
            outputs = self.inference_session.run(
                [self.refined_output_name],
                {self.input_name: image_array},
            )
            if len(outputs) != 1:
                raise RuntimeError(
                    'Camie Tagger v2 returned an unexpected ONNX result.'
                )
            refined_output = outputs[0]
        else:
            outputs = self.inference_session.run(
                None,
                {self.input_name: image_array},
            )
            if (self.refined_output_index is None
                    or len(outputs) <= self.refined_output_index):
                raise RuntimeError(
                    'Camie Tagger v2 did not return its refined prediction '
                    'tensor.'
                )
            refined_output = outputs[self.refined_output_index]

        logits = np.asarray(refined_output)
        if logits.ndim != 2 or logits.shape[0] < 1:
            raise RuntimeError(
                'Camie Tagger v2 returned refined predictions with an '
                f'unexpected shape: {logits.shape}.'
            )
        if logits.shape[1] != len(self.tags):
            raise RuntimeError(
                'Camie Tagger v2 returned '
                f'{logits.shape[1]} scores for {len(self.tags)} tags.'
            )

        logits = logits[0].astype(np.float32, copy=False)
        probabilities = 1.0 / (
            1.0 + np.exp(-np.clip(logits, -88.0, 88.0))
        )
        tags_to_exclude = set(get_tags_to_exclude(
            wd_tagger_settings['tags_to_exclude']
        ))
        minimum_probability = wd_tagger_settings['min_probability']

        tags_and_probabilities = []
        for tag, category, probability in zip(
                self.tags, self.categories, probabilities):
            if category in EXCLUDED_CATEGORIES:
                continue
            if (not np.isfinite(probability)
                    or probability < minimum_probability
                    or tag in tags_to_exclude):
                continue
            tags_and_probabilities.append((tag, float(probability)))

        tags_and_probabilities.sort(key=lambda item: item[1], reverse=True)
        tags_and_probabilities = tags_and_probabilities[
            :wd_tagger_settings['max_tags']
        ]
        if not tags_and_probabilities:
            return (), ()
        tags, probabilities = zip(*tags_and_probabilities)
        return tags, probabilities


class CamieTagger(WdTagger):
    image_mode = 'RGB'
    model_artifact_kind = MODEL_ARTIFACT_KIND_CAMIE_TAGGER
    supports_structured_output = False

    @classmethod
    def get_download_revision(cls, model_id: str) -> str | None:
        if str(model_id).casefold() == CAMIE_TAGGER_MODEL_ID.casefold():
            return CAMIE_TAGGER_REVISION
        return None

    def get_error_message(self) -> str | None:
        if _ONNXRUNTIME_IMPORT_ERROR is not None:
            return (
                'Camie Tagger v2 is unavailable because onnxruntime failed '
                f'to import. Original error: {_ONNXRUNTIME_IMPORT_ERROR}'
            )
        return None

    def get_model(self):
        return CamieTaggerModel(
            self.model_id,
            use_gpu=self.device.type == 'cuda',
            gpu_index=self.caption_settings['gpu_index'],
        )

    def get_model_inputs(
            self,
            image_prompt: str,
            image: Image,
            crop: bool) -> np.ndarray:
        pil_image = self.load_image(image, crop)
        return preprocess_camie_image(pil_image, self.model.image_size)
