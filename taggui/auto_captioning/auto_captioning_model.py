import gc
import json
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from time import perf_counter, sleep

import cv2
import numpy as np
import torch
import pillow_jxl
from PIL import Image as PilImage, UnidentifiedImageError
from PIL.ImageOps import exif_transpose
from transformers import AutoProcessor, BatchFeature, BitsAndBytesConfig
try:
    from transformers import AutoModelForImageTextToText as AutoModelForVision2Seq
except ImportError:
    from transformers import AutoModelForVision2Seq
from transformers.utils.import_utils import is_torch_bf16_gpu_available

import auto_captioning.captioning_thread as captioning_thread
from auto_captioning.model_availability import (
    MODEL_ARTIFACT_KIND_HUGGINGFACE,
    MODEL_ARTIFACT_KIND_WD_TAGGER,
    clear_model_availability_cache,
    get_model_install_state,
    get_models_directory_target_path,
)
from models.image_list_model import _video_lock
from utils.enums import CaptionDevice
from utils.image import Image


class CaptionGenerationError(RuntimeError):
    def __init__(self, message: str, console_output: str | None = None):
        super().__init__(message)
        self.console_output = console_output


def replace_template_variable(match: re.Match, image: Image, skip_hash: bool) -> str:
    template_variable = match.group(0)[1:-1].lower()
    if template_variable == 'tags':
        if skip_hash:
            return ', '.join([t for t in image.tags if not t.startswith('#')])
        else:
            return ', '.join(image.tags)
    if template_variable == 'name':
        return image.path.stem
    if template_variable in ('directory', 'folder'):
        return image.path.parent.name


def replace_template_variables(text: str, image: Image, skip_hash: bool) -> str:
    # Replace template variables inside curly braces that are not escaped.
    text = re.sub(r'(?<!\\){[^{}]+(?<!\\)}',
                  lambda match: replace_template_variable(match, image, skip_hash), text)
    # Unescape escaped curly braces.
    text = re.sub(r'\\([{}])', r'\1', text)
    return text


_HF_DOWNLOAD_HELPER_SCRIPT = r"""
import json
import sys
import traceback
from pathlib import Path

from huggingface_hub import hf_hub_download, snapshot_download


payload = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
result_path = Path(sys.argv[2])
error_path = Path(sys.argv[3])

try:
    mode = payload.pop('mode')
    if mode == 'snapshot':
        result = snapshot_download(**payload)
    elif mode == 'files':
        repo_id = payload.pop('repo_id')
        filenames = payload.pop('filenames')
        local_dir = payload.get('local_dir')
        last_path = ''
        for filename in filenames:
            last_path = hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                **payload,
            )
        result = local_dir or str(Path(last_path).parent)
    else:
        raise RuntimeError(f'Unsupported download mode: {mode}')
    result_path.write_text(str(result or ''), encoding='utf-8')
except Exception:
    error_path.write_text(traceback.format_exc(), encoding='utf-8')
    raise
"""


class AutoCaptioningModel:
    dtype = torch.float16
    # When loading a model, if the `use_safetensors` argument is not set and
    # both a safetensors and a non-safetensors version of the model are
    # available, both versions get downloaded. This should be set to `None` for
    # models that do not have a safetensors version.
    use_safetensors = True
    model_load_context_manager = nullcontext()
    transformers_model_class = AutoModelForVision2Seq
    image_mode = 'RGB'
    model_artifact_kind = MODEL_ARTIFACT_KIND_HUGGINGFACE

    def __init__(self,
                 captioning_thread_: 'captioning_thread.CaptioningThread',
                 caption_settings: dict,
                 image_viewer: 'ImageViewer' = None):
        self.thread = captioning_thread_
        self.thread_parent = captioning_thread_.parent()
        self.image_viewer = image_viewer
        self.caption_settings = caption_settings
        self.model_id = caption_settings['model_id']
        self.requested_model_id = self.model_id
        self.prompt = caption_settings['prompt']
        self.skip_hash = caption_settings['skip_hash']
        self.caption_start = caption_settings['caption_start']
        self.device_setting: CaptionDevice = caption_settings['device']
        self.device: torch.device = self.get_device()
        if self.dtype == torch.bfloat16:
            if self.device.type != 'cuda' or not is_torch_bf16_gpu_available():
                self.dtype = torch.float16
        self.dtype_argument = ({'dtype': self.dtype}
                               if self.device.type == 'cuda' else {})
        self.load_in_4_bit = caption_settings['load_in_4_bit']
        self.bad_words_string = caption_settings['bad_words']
        self.forced_words_string = caption_settings['forced_words']
        self.remove_tag_separators = caption_settings['remove_tag_separators']
        self.remove_new_lines = caption_settings['remove_new_lines']
        self.generation_parameters = caption_settings['generation_parameters']
        self.beam_count = self.generation_parameters['num_beams']
        self.processor = None
        self.model = None
        self.tokenizer = None

    def get_device(self) -> torch.device:
        if (self.device_setting == CaptionDevice.GPU
                and torch.cuda.is_available()):
            gpu_index = self.caption_settings['gpu_index']
            device = torch.device(f'cuda:{gpu_index}')
        else:
            device = torch.device('cpu')
        return device

    def get_additional_error_message(self) -> str | None:
        return None

    def get_error_message(self) -> str | None:
        if self.forced_words_string.strip() and self.beam_count < 2:
            return ('`Number of beams` must be greater than 1 when `Include '
                    'in caption` is not empty.')
        return self.get_additional_error_message()

    def get_processor(self):
        return AutoProcessor.from_pretrained(self.model_id,
                                             trust_remote_code=True)

    @classmethod
    def get_download_revision(cls, model_id: str) -> str | None:
        return None

    def get_model_load_arguments(self) -> dict:
        arguments = {'device_map': self.device, 'trust_remote_code': True,
                     'use_safetensors': self.use_safetensors}
        if self.load_in_4_bit:
            quantization_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type='nf4',
                bnb_4bit_compute_dtype=self.dtype,
                bnb_4bit_quant_storage=self.dtype,
                bnb_4bit_use_double_quant=True
            )
            arguments['quantization_config'] = quantization_config
        if self.device.type == 'cuda':
            arguments['torch_dtype'] = self.dtype
        return arguments

    def load_model(self, model_load_arguments: dict):
        with self.model_load_context_manager:
            model = self.transformers_model_class.from_pretrained(
                self.model_id, **model_load_arguments)
        model.eval()
        return model

    def patch_source_code(self) -> bool:
        # Return `True` if the source code was patched.
        return False

    def get_model(self):
        model_load_arguments = self.get_model_load_arguments()
        model = self.load_model(model_load_arguments)
        if self.patch_source_code():
            print('Patched the model source code. Reloading the model...')
            model = self.load_model(model_load_arguments)
        return model

    def get_snapshot_download_allow_patterns(self) -> list[str]:
        return [
            '*.json',
            '*.txt',
            '*.model',
            '*.py',
            '*.tiktoken',
            '*.safetensors',
            '*.safetensors.index.json',
            '*.bin',
            '*.bin.index.json',
            '*.onnx',
            '*.gguf',
            '*.pt',
            '*.pth',
            'tokenizer*',
            'vocab*',
            'merges.txt',
            'special_tokens_map.json',
            'added_tokens.json',
            'processor_config.json',
            'preprocessor_config.json',
            'image_processor*.json',
            'feature_extractor*.json',
        ]

    def get_snapshot_download_ignore_patterns(self) -> list[str] | None:
        if self.use_safetensors is True:
            return ['*.bin', '*.bin.index.json']
        if self.use_safetensors is False:
            return ['*.safetensors', '*.safetensors.index.json']
        return None

    def _resolve_model_id_for_loading(self) -> str | None:
        revision = self.get_download_revision(self.requested_model_id)
        install_state = get_model_install_state(
            self.requested_model_id,
            self.thread.models_directory_path,
            artifact_kind=self.model_artifact_kind,
            revision=revision,
        )

        if install_state.source == 'local_path':
            if install_state.installed and install_state.path is not None:
                return str(install_state.path)
            raise RuntimeError(
                f'Local model path is incomplete: {install_state.path}'
            )

        if install_state.installed:
            if (install_state.source == 'models_directory'
                    and install_state.path is not None):
                return str(install_state.path)
            return self.requested_model_id

        self._download_model_assets(
            self.requested_model_id,
            revision=revision,
            resumable=install_state.status == 'partial',
        )
        if self.thread.is_canceled:
            return None

        clear_model_availability_cache()
        refreshed_install_state = get_model_install_state(
            self.requested_model_id,
            self.thread.models_directory_path,
            artifact_kind=self.model_artifact_kind,
            revision=revision,
        )
        if (refreshed_install_state.installed
                and refreshed_install_state.source == 'models_directory'
                and refreshed_install_state.path is not None):
            return str(refreshed_install_state.path)
        return self.requested_model_id

    def _download_model_assets(self, model_id: str, *,
                               revision: str | None,
                               resumable: bool):
        target_dir = get_models_directory_target_path(
            self.thread.models_directory_path,
            model_id,
        )
        target_dir_existed = bool(target_dir and target_dir.exists())
        self.thread.current_stage = 'downloading_model'
        if resumable:
            print(f'Resuming model download for {model_id}...')
        else:
            print(f'Downloading model files for {model_id}...')

        if self.model_artifact_kind == MODEL_ARTIFACT_KIND_WD_TAGGER:
            payload = {
                'mode': 'files',
                'repo_id': model_id,
                'filenames': ['model.onnx', 'selected_tags.csv'],
                'revision': revision,
            }
        else:
            payload = {
                'mode': 'snapshot',
                'repo_id': model_id,
                'revision': revision,
                'allow_patterns': self.get_snapshot_download_allow_patterns(),
                'ignore_patterns': self.get_snapshot_download_ignore_patterns(),
            }
        if target_dir is not None:
            target_dir.mkdir(parents=True, exist_ok=True)
            payload['local_dir'] = str(target_dir)

        self._run_cancelable_hf_download(
            payload,
            model_id=model_id,
            cleanup_dir=target_dir,
            cleanup_dir_existed=target_dir_existed,
        )
        self.thread.current_stage = 'loading_model'
        if not self.thread.is_canceled:
            print(f'Finished downloading {model_id}.')

    def _run_cancelable_hf_download(self, payload: dict, *,
                                    model_id: str,
                                    cleanup_dir: Path | None,
                                    cleanup_dir_existed: bool):
        temp_dir = Path(tempfile.mkdtemp(prefix='taggui-model-download-'))
        payload_path = temp_dir / 'payload.json'
        result_path = temp_dir / 'result.txt'
        error_path = temp_dir / 'error.txt'
        payload_path.write_text(json.dumps(payload), encoding='utf-8')

        process = subprocess.Popen(
            [sys.executable, '-u', '-c', _HF_DOWNLOAD_HELPER_SCRIPT,
             str(payload_path), str(result_path), str(error_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.thread.set_external_process(process)
        try:
            while True:
                if self.thread.is_canceled:
                    self.thread.cancel_external_process()
                    self._cleanup_incomplete_local_download(
                        cleanup_dir,
                        cleanup_dir_existed,
                    )
                    clear_model_availability_cache()
                    print(f'Canceled downloading {model_id}.')
                    return
                try:
                    process.wait(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    sleep(0.05)
                    continue

            if process.returncode != 0:
                error_text = ''
                if error_path.is_file():
                    error_text = error_path.read_text(
                        encoding='utf-8',
                        errors='replace',
                    ).strip()
                if cleanup_dir is not None and not cleanup_dir_existed:
                    self._cleanup_incomplete_local_download(
                        cleanup_dir,
                        cleanup_dir_existed,
                    )
                raise RuntimeError(
                    f'Failed downloading model files for {model_id}.\n'
                    f'{error_text}'.rstrip()
                )
        finally:
            self.thread.clear_external_process(process)
            shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def _cleanup_incomplete_local_download(target_dir: Path | None,
                                           target_dir_existed: bool):
        if target_dir is None or target_dir_existed:
            return
        shutil.rmtree(target_dir, ignore_errors=True)

    def load_processor_and_model(self):
        resolved_model_id = self._resolve_model_id_for_loading()
        if resolved_model_id is None:
            return
        self.model_id = resolved_model_id
        # If the processor and model were previously loaded, use them.
        processor = self.thread_parent.processor
        model = self.thread_parent.model
        # Only GPUs support 4-bit quantization.
        self.load_in_4_bit = self.load_in_4_bit and self.device.type == 'cuda'
        if (model and self.thread_parent.model_id == self.model_id
                and (self.thread_parent.model_device_type
                     == self.device.type)
                and (self.thread_parent.is_model_loaded_in_4_bit
                     == self.load_in_4_bit)):
            self.processor = processor
            self.model = model
            return
        # Load the new processor and model.
        if model:
            # Garbage collect the previous processor and model to free up
            # memory.
            self.thread_parent.processor = None
            self.thread_parent.model = None
            del processor
            del model
            gc.collect()
        self.thread.clear_console_text_edit_requested.emit()
        print(f'Loading {self.model_id}...')
        self.processor = self.get_processor()
        self.thread_parent.processor = self.processor
        self.model = self.get_model()
        self.thread_parent.model = self.model
        self.thread_parent.model_id = self.model_id
        self.thread_parent.model_device_type = self.device.type
        self.thread_parent.is_model_loaded_in_4_bit = self.load_in_4_bit

    def monkey_patch_after_loading(self):
        return

    @staticmethod
    def get_generation_text() -> str:
        return 'Captioning'

    @staticmethod
    def get_default_prompt() -> str:
        return ''

    @staticmethod
    def format_prompt(prompt: str) -> str:
        return prompt

    def get_image_prompt(self, image: Image) -> str | None:
        if self.prompt:
            image_prompt = replace_template_variables(self.prompt, image,
                                                      self.skip_hash)
        else:
            self.prompt = self.get_default_prompt()
            image_prompt = self.prompt
        image_prompt = self.format_prompt(image_prompt)
        return image_prompt

    def get_input_text(self, image_prompt: str) -> str:
        if image_prompt and self.caption_start:
            text = f'{image_prompt} {self.caption_start}'
        else:
            text = image_prompt or self.caption_start
        return text

    @staticmethod
    def _get_marked_video_start_frame(image: Image) -> int:
        if isinstance(getattr(image, 'loop_start_frame', None), int):
            return max(0, int(image.loop_start_frame))

        viewer_markers = getattr(image, 'viewer_loop_markers', None)
        if not isinstance(viewer_markers, dict):
            return 0

        for scope in ('main', 'floating_last'):
            marker = viewer_markers.get(scope)
            if isinstance(marker, dict) and isinstance(marker.get('loop_start_frame'), int):
                return max(0, int(marker['loop_start_frame']))

        for marker in viewer_markers.values():
            if isinstance(marker, dict) and isinstance(marker.get('loop_start_frame'), int):
                return max(0, int(marker['loop_start_frame']))

        return 0

    def _load_video_frame(self, image: Image, crop: bool) -> PilImage:
        target_frame = self._get_marked_video_start_frame(image)

        with _video_lock:
            cap = cv2.VideoCapture(str(image.path), cv2.CAP_FFMPEG)
            cap.set(cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_NONE)
            if not cap.isOpened():
                raise UnidentifiedImageError(
                    f'Could not open video for captioning: {image.path.name}'
                )

            try:
                frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                if frame_count > 0:
                    target_frame = min(target_frame, frame_count - 1)

                cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
                ret, frame = cap.read()
                if not ret or frame is None:
                    raise UnidentifiedImageError(
                        f'Could not extract frame {target_frame} from video: {image.path.name}'
                    )
            finally:
                cap.release()

        pil_image = PilImage.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), mode='RGB')
        pil_image = pil_image.convert(self.image_mode)
        if crop and image.crop is not None:
            pil_image = pil_image.crop(image.crop.getCoords())
        return pil_image

    def _should_use_current_viewer_video_frame(self, image: Image) -> bool:
        if self.image_viewer is None:
            return False
        if len(getattr(self.thread, 'selected_image_indices', [])) != 1:
            return False
        if not bool(getattr(self.image_viewer, '_is_video_loaded', False)):
            return False

        video_player = getattr(self.image_viewer, 'video_player', None)
        if video_player is None or getattr(video_player, 'video_path', None) is None:
            return False

        return str(video_player.video_path) == str(image.path)

    def _load_current_viewer_video_frame(self, image: Image, crop: bool) -> PilImage:
        video_player = self.image_viewer.video_player
        frame_array = video_player.get_current_frame_as_numpy()
        if frame_array is None:
            raise UnidentifiedImageError(
                f'Could not extract current viewer frame from video: {image.path.name}'
            )

        pil_image = PilImage.fromarray(frame_array, mode='RGB')
        pil_image = pil_image.convert(self.image_mode)
        if crop and image.crop is not None:
            pil_image = pil_image.crop(image.crop.getCoords())
        return pil_image

    def load_image(self, image: Image, crop: bool) -> PilImage:
        if image.is_video:
            if self._should_use_current_viewer_video_frame(image):
                return self._load_current_viewer_video_frame(image, crop)
            return self._load_video_frame(image, crop)

        # Handle regular image files
        pil_image = PilImage.open(image.path)
        # Rotate the image according to the orientation tag.
        pil_image = exif_transpose(pil_image)
        pil_image = pil_image.convert(self.image_mode)
        if crop and image.crop is not None:
            pil_image = pil_image.crop(image.crop.getCoords())
        return pil_image

    def get_model_inputs(self, image_prompt: str, image: Image,
                         crop: bool) -> BatchFeature | dict | np.ndarray:
        text = self.get_input_text(image_prompt)
        pil_image = self.load_image(image, crop)
        model_inputs = (self.processor(text=text, images=pil_image,
                                       return_tensors='pt')
                        .to(self.device, **self.dtype_argument))
        return model_inputs

    def get_generation_model(self):
        return self.model

    def get_tokenizer(self):
        return self.processor.tokenizer

    def get_bad_words_ids(self) -> list[list[int]] | None:
        if not self.bad_words_string.strip():
            return None
        words = re.split(r'(?<!\\),', self.bad_words_string)
        words = [word.strip() for word in words if word.strip()]
        if not words:
            return None
        words = [word.replace(r'\,', ',') for word in words]
        # Also discourage generating the versions of the words with spaces
        # before them.
        words += [' ' + word for word in words]
        bad_words_ids = self.tokenizer(words,
                                       add_special_tokens=False).input_ids
        return bad_words_ids

    def get_forced_words_ids(self) -> list[list[list[int]]] | None:
        if not self.forced_words_string.strip():
            return None
        word_groups = re.split(r'(?<!\\),', self.forced_words_string)
        forced_words_ids = []
        for word_group in word_groups:
            word_group = word_group.strip().replace(r'\,', ',')
            words = re.split(r'(?<!\\)\|', word_group)
            words = [word.strip() for word in words if word.strip()]
            if not words:
                continue
            words = [word.replace(r'\|', '|') for word in words]
            words_ids = self.tokenizer(words,
                                       add_special_tokens=False).input_ids
            forced_words_ids.append(words_ids)
        if not forced_words_ids:
            return None
        return forced_words_ids

    @staticmethod
    def get_additional_generation_parameters() -> dict:
        return {}

    @staticmethod
    def postprocess_image_prompt(image_prompt: str) -> str:
        return image_prompt

    @staticmethod
    def postprocess_generated_text(generated_text: str) -> str:
        return generated_text

    def estimate_output_token_count(self, caption: str) -> int | None:
        tokenizer = getattr(self, 'tokenizer', None)
        if tokenizer is None:
            return None
        try:
            token_ids = tokenizer(caption, add_special_tokens=False).input_ids
        except Exception:
            return None
        if isinstance(token_ids, list):
            if token_ids and isinstance(token_ids[0], list):
                return len(token_ids[0])
            return len(token_ids)
        return None

    @staticmethod
    def format_console_output(raw_output: str | None,
                              saved_caption: str | None) -> str:
        raw_text = (raw_output or '').strip()
        saved_text = (saved_caption or '').strip()
        if raw_text and saved_text and raw_text != saved_text:
            return (
                f'Raw model output:\n{raw_text}\n\n'
                f'Saved caption:\n{saved_text}'
            )
        return saved_text or raw_text

    @staticmethod
    def format_incomplete_console_output(raw_output: str | None,
                                         note: str | None = None) -> str:
        parts = []
        raw_text = (raw_output or '').strip()
        note_text = (note or '').strip()
        if raw_text:
            parts.append(f'Partial model output:\n{raw_text}')
        if note_text:
            parts.append(note_text)
        return '\n\n'.join(parts).strip()

    def get_console_generated_token_ids(
            self, generated_token_ids: torch.Tensor) -> torch.Tensor:
        return generated_token_ids

    def decode_generated_text(self, generated_token_ids: torch.Tensor) -> str:
        generated_token_ids = self.get_console_generated_token_ids(
            generated_token_ids)
        generated_text = self.processor.batch_decode(
            generated_token_ids, skip_special_tokens=True)[0]
        generated_text = self.postprocess_generated_text(generated_text)
        return generated_text.strip()

    def get_caption_from_generated_tokens(
            self, generated_token_ids: torch.Tensor, image_prompt: str) -> str:
        generated_text = self.decode_generated_text(generated_token_ids)
        image_prompt = self.postprocess_image_prompt(image_prompt)
        if image_prompt.strip() and generated_text.startswith(image_prompt):
            caption = generated_text[len(image_prompt):]
        elif (self.caption_start.strip()
              and generated_text.startswith(self.caption_start)):
            caption = generated_text
        else:
            caption = f'{self.caption_start.strip()} {generated_text.strip()}'
        caption = caption.strip()
        if self.remove_tag_separators:
            caption = caption.replace(self.thread.tag_separator, ' ')
        if self.remove_new_lines:
            caption = caption.replace('\n', ' ')
            caption = re.sub(r' +', ' ', caption)
        return caption

    def generate_caption(self, model_inputs: BatchFeature | dict | np.ndarray,
                         image_prompt: str) -> tuple[str, str]:
        generation_model = self.get_generation_model()
        self.tokenizer = self.get_tokenizer()
        bad_words_ids = self.get_bad_words_ids()
        forced_words_ids = self.get_forced_words_ids()
        additional_generation_parameters = (
            self.get_additional_generation_parameters())
        generation_start = perf_counter()
        with torch.inference_mode():
            generated_token_ids = generation_model.generate(
                **model_inputs, bad_words_ids=bad_words_ids,
                force_words_ids=forced_words_ids, **self.generation_parameters,
                **additional_generation_parameters)
        generation_duration = perf_counter() - generation_start
        raw_console_output = self.decode_generated_text(generated_token_ids)
        caption = self.get_caption_from_generated_tokens(generated_token_ids,
                                                         image_prompt)
        self.thread.record_generation_metrics(
            self.estimate_output_token_count(caption),
            generation_duration,
        )
        console_output_caption = self.format_console_output(
            raw_console_output,
            caption,
        )
        return caption, console_output_caption
