import re
from time import perf_counter

import torch
from transformers import AutoProcessor
try:
    from transformers import AutoModelForImageTextToText as AutoModelForVision2Seq
except ImportError:
    from transformers import AutoModelForVision2Seq

from auto_captioning.auto_captioning_model import (
    AutoCaptioningModel,
    CaptionGenerationError,
)
from utils.image import Image

try:
    from transformers import Qwen2_5_VLForConditionalGeneration
    _HAS_QWEN25_VL_CLASS = True
except ImportError:
    _HAS_QWEN25_VL_CLASS = False

try:
    from qwen_vl_utils import process_vision_info as _process_vision_info
    _HAS_QWEN_VL_UTILS = True
except ImportError:
    _HAS_QWEN_VL_UTILS = False


def _process_vision_info_compat(messages):
    """Wrapper that handles both old and new qwen-vl-utils API signatures."""
    try:
        return _process_vision_info(messages, return_video_kwargs=True)
    except TypeError:
        image_inputs, video_inputs = _process_vision_info(messages)
        return image_inputs, video_inputs, {}


class QwenVL(AutoCaptioningModel):
    """
    Native local captioning for Qwen2.5-VL and Qwen3.5 vision-language models.

    Supports genuine VIDEO understanding via temporal position encoding (TMRoPE).
    The model understands motion, action sequences, and events over time.

    Supported model IDs:
        Qwen/Qwen2.5-VL-3B-Instruct    (~6 GB VRAM FP16, ~3.5 GB Q4)
        Qwen/Qwen2.5-VL-7B-Instruct    (~14 GB VRAM FP16, ~5 GB Q4)
        Qwen/Qwen3.5-4B                (~8 GB VRAM FP16, ~4 GB Q4)
        Qwen/Qwen3.5-9B                (~18 GB VRAM FP16, ~10 GB Q4)

    Requires: pip install qwen-vl-utils
    """

    dtype = torch.bfloat16

    def get_additional_error_message(self) -> str | None:
        if not _HAS_QWEN_VL_UTILS:
            return (
                'The qwen-vl-utils package is required for Qwen VL models. '
                'Install it with: pip install qwen-vl-utils'
            )
        return None

    def get_processor(self):
        return AutoProcessor.from_pretrained(self.model_id, trust_remote_code=True)

    def load_model(self, model_load_arguments: dict):
        lowercase_id = self.model_id.lower()
        if 'qwen2.5-vl' in lowercase_id and _HAS_QWEN25_VL_CLASS:
            model_class = Qwen2_5_VLForConditionalGeneration
        else:
            model_class = AutoModelForVision2Seq
        try:
            with self.model_load_context_manager:
                model = model_class.from_pretrained(
                    self.model_id, **model_load_arguments)
        except (ValueError, KeyError) as e:
            msg = str(e)
            if ('does not recognize this architecture' in msg
                    or 'qwen3' in msg.lower()):
                raise RuntimeError(
                    f'Your transformers version is too old to load '
                    f'{self.model_id}.\n'
                    f'Upgrade with: pip install --upgrade transformers\n'
                    f'Original error: {e}'
                ) from e
            raise
        model.eval()
        return model

    def get_tokenizer(self):
        return self.processor.tokenizer

    @staticmethod
    def get_default_prompt() -> str:
        return 'Describe this image in detail.'

    @staticmethod
    def get_default_video_prompt() -> str:
        return ('Describe what happens in this video in detail. Include the '
                'sequence of events, actions, motion, and any notable changes '
                'over time.')

    def _build_messages(self, image_prompt: str, image: Image, crop: bool) -> list:
        video_fps = float(self.caption_settings.get('video_fps', 1.0))
        video_max_frames = int(self.caption_settings.get('video_max_frames', 16))
        
        if image.is_video:
            prompt = image_prompt or self.get_default_video_prompt()
            video_content = {
                'type': 'video',
                'video': str(image.path),
                'fps': video_fps,
                'max_pixels': 360 * 640,
            }
            if video_max_frames > 0:
                video_content['max_frames'] = video_max_frames
            content = [video_content, {'type': 'text', 'text': prompt}]
        else:
            pil_image = self.load_image(image, crop)
            prompt = image_prompt or self.get_default_prompt()
            content = [
                {'type': 'image', 'image': pil_image},
                {'type': 'text', 'text': prompt},
            ]
        return [
            {
                'role': 'system',
                'content': self.caption_settings.get('system_prompt', '').strip()
            },
            {'role': 'user', 'content': content}
        ]

    def get_model_inputs(self, image_prompt: str, image: Image, crop: bool):
        messages = self._build_messages(image_prompt, image, crop)
        disable_thinking = self.caption_settings.get('disable_thinking', True)
        # enable_thinking=False tells Qwen3.5 to skip its internal reasoning
        # chain entirely, making generation 2-5x faster for simple captions.
        # Qwen2.5-VL ignores this kwarg gracefully (no-op).
        try:
            text = self.processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True,
                enable_thinking=not disable_thinking)
        except TypeError:
            # Older processor versions don't support enable_thinking — fall back
            text = self.processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True)
        image_inputs, video_inputs, video_kwargs = _process_vision_info_compat(messages)
        
        # New transformers processors (Qwen2.5-VL/Qwen3-VL) strictly type check kwargs.
        # qwen-vl-utils may return 'fps' as a list (e.g. [1.0] or []).
        # Processor expects a single float/int or None.
        if 'fps' in video_kwargs:
            val = video_kwargs['fps']
            if isinstance(val, list):
                if len(val) == 1:
                    video_kwargs['fps'] = val[0]
                else:
                    # Remove empty list or multi-item lists which are invalid for single-sequence processing
                    video_kwargs.pop('fps')
            elif val is None:
                 video_kwargs.pop('fps')

        if image.is_video:
            fps = float(self.caption_settings.get('video_fps', 1.0))
            print(f'QwenVL: processing video at {fps:.1f} fps — {image.path.name}')
        inputs = self.processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors='pt',
            **video_kwargs,
        ).to(self.device, **self.dtype_argument)
        return inputs

    def generate_caption(self, model_inputs, image_prompt: str) -> tuple[str, str]:
        gen_params = self.generation_parameters
        self.tokenizer = self.get_tokenizer()
        gen_kwargs = {
            'max_new_tokens': gen_params.get('max_new_tokens', 256),
            'do_sample': gen_params.get('do_sample', False),
            'num_beams': gen_params.get('num_beams', 1),
            'repetition_penalty': gen_params.get('repetition_penalty', 1.0),
            'length_penalty': gen_params.get('length_penalty', 1.0),
        }
        if gen_kwargs['do_sample']:
            gen_kwargs['temperature'] = gen_params.get('temperature', 1.0)
            gen_kwargs['top_p'] = gen_params.get('top_p', 1.0)

        generation_start = perf_counter()
        with torch.inference_mode():
            generated_ids = self.model.generate(**model_inputs, **gen_kwargs)
        generation_duration = perf_counter() - generation_start

        # Qwen2.5-VL returns the full sequence including input — trim prefix
        generated_ids_trimmed = [
            out_ids[len(in_ids):]
            for in_ids, out_ids in zip(model_inputs.input_ids, generated_ids)
        ]
        raw_output = self.processor.batch_decode(
            generated_ids_trimmed,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )[0].strip()
        
        # Safeguard: if the model hit the token limit, it was cut off mid-thought or mid-sentence
        if len(generated_ids_trimmed[0]) >= gen_kwargs['max_new_tokens'] - 1:
            self.thread.record_generation_metrics(
                self.estimate_output_token_count(raw_output),
                generation_duration,
            )
            raise CaptionGenerationError(
                f"Generation reached the token limit of {gen_kwargs['max_new_tokens']} "
                f"and was cut off early!\n"
                f"Please open 'Advanced Settings' and increase 'Maximum tokens' "
                f"(e.g., to 1024 or 2048) to give the model time to finish.",
                console_output=self.format_incomplete_console_output(
                    raw_output,
                    note=(
                        f'Generation stopped after reaching the configured '
                        f'limit of {gen_kwargs["max_new_tokens"]} new tokens.'
                    ),
                ),
            )

        caption = raw_output

        if self.caption_start and self.caption_start.strip():
            caption = f'{self.caption_start.strip()} {caption}'

        # Qwen3.5 is a reasoning model - it may output <think>...</think> before the answer.
        # Only strip if thinking was enabled (disable_thinking=False).
        disable_thinking = self.caption_settings.get('disable_thinking', True)
        if not disable_thinking and '</think>' in caption:
            caption = caption.split('</think>')[-1].strip()

        if self.remove_tag_separators:
            caption = caption.replace(self.thread.tag_separator, ' ')
        if self.remove_new_lines:
            caption = caption.replace('\n', ' ')
            caption = re.sub(r' +', ' ', caption)

        self.thread.record_generation_metrics(
            self.estimate_output_token_count(caption),
            generation_duration,
        )
        return caption, self.format_console_output(raw_output, caption)
