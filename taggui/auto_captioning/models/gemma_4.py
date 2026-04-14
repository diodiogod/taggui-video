import re
from time import perf_counter

import torch

try:
    from transformers import AutoModelForMultimodalLM
    _HAS_MULTIMODAL_LM = True
except ImportError:
    AutoModelForMultimodalLM = None
    _HAS_MULTIMODAL_LM = False

from auto_captioning.auto_captioning_model import AutoCaptioningModel
from utils.image import Image


class Gemma4(AutoCaptioningModel):
    """
    Native local captioning for Gemma 4 multimodal models.

    Supported model IDs:
        google/gemma-4-E2B-it
        google/gemma-4-E4B-it
        google/gemma-4-26B-A4B-it
        google/gemma-4-31B-it

    Notes:
        - All Gemma 4 models support text + image input.
        - Video input is supported via the native Transformers video pipeline.
        - Audio support is limited to the E2B and E4B variants, but TagGUI's
          local captioning flow currently only uses image/video inputs.
    """

    dtype = torch.bfloat16
    transformers_model_class = AutoModelForMultimodalLM

    def get_additional_error_message(self) -> str | None:
        if not _HAS_MULTIMODAL_LM:
            return (
                'Your transformers version is too old to load Gemma 4 '
                'multimodal models.\n'
                'Upgrade with: pip install --upgrade transformers'
            )
        return None

    def load_model(self, model_load_arguments: dict):
        if not _HAS_MULTIMODAL_LM:
            raise RuntimeError(
                'Gemma 4 multimodal loading requires a newer transformers '
                'version with AutoModelForMultimodalLM support.'
            )
        try:
            return super().load_model(model_load_arguments)
        except (ValueError, KeyError) as e:
            msg = str(e).lower()
            if ('does not recognize this architecture' in msg
                    or 'gemma4' in msg):
                raise RuntimeError(
                    f'Your transformers version is too old to load '
                    f'{self.model_id}.\n'
                    f'Upgrade with: pip install --upgrade transformers\n'
                    f'Original error: {e}'
                ) from e
            raise

    @staticmethod
    def get_default_prompt() -> str:
        return 'Describe this image in detail.'

    @staticmethod
    def get_default_video_prompt() -> str:
        return ('Describe what happens in this video in detail. Include the '
                'sequence of events, actions, motion, and any notable changes '
                'over time.')

    def _build_messages(self, image_prompt: str, image: Image, crop: bool) -> list[dict]:
        prompt = image_prompt or (
            self.get_default_video_prompt() if image.is_video
            else self.get_default_prompt()
        )
        if image.is_video:
            content = [
                {'type': 'video', 'video': str(image.path)},
                {'type': 'text', 'text': prompt},
            ]
        else:
            pil_image = self.load_image(image, crop)
            content = [
                {'type': 'image', 'image': pil_image},
                {'type': 'text', 'text': prompt},
            ]

        messages = []
        system_prompt = self.caption_settings.get('system_prompt', '').strip()
        if system_prompt:
            messages.append({
                'role': 'system',
                'content': [{'type': 'text', 'text': system_prompt}],
            })
        messages.append({'role': 'user', 'content': content})
        return messages

    def _apply_chat_template(self, messages: list[dict], image: Image):
        template_kwargs = {
            'tokenize': True,
            'return_dict': True,
            'return_tensors': 'pt',
            'add_generation_prompt': True,
        }

        disable_thinking = self.caption_settings.get('disable_thinking', True)
        thinking_kwargs = []
        if disable_thinking is not None:
            thinking_kwargs = [{'enable_thinking': not disable_thinking}, {}]
        else:
            thinking_kwargs = [{}]

        video_kwargs_attempts = [{}]
        if image.is_video:
            video_fps = float(self.caption_settings.get('video_fps', 1.0))
            video_max_frames = int(self.caption_settings.get('video_max_frames', 16))
            frame_cap_label = (
                f'up to {video_max_frames} frames'
                if video_max_frames > 0 else 'automatic frame count'
            )
            print(
                f'Gemma4: processing video at {video_fps:.1f} fps with '
                f'{frame_cap_label} - {image.path.name}'
            )
            # Keep native video input, but prefer OpenCV as the decoding backend
            # to avoid dragging torchcodec into TagGUI's local dependency stack.
            video_kwargs_attempts = []
            if video_max_frames > 0:
                video_kwargs_attempts.extend([
                    {
                        'video_load_backend': 'opencv',
                        'video_fps': video_fps,
                        'num_frames': video_max_frames,
                    },
                    {
                        'video_load_backend': 'opencv',
                        'num_frames': video_max_frames,
                    },
                ])
            video_kwargs_attempts.extend([
                {
                    'video_load_backend': 'opencv',
                    'video_fps': video_fps,
                },
                {'video_fps': video_fps},
            ])
            if video_max_frames > 0:
                video_kwargs_attempts.extend([
                    {'video_fps': video_fps, 'num_frames': video_max_frames},
                    {'num_frames': video_max_frames},
                ])

        last_error = None
        for video_kwargs in video_kwargs_attempts:
            for extra_kwargs in thinking_kwargs:
                try:
                    return self.processor.apply_chat_template(
                        messages,
                        **template_kwargs,
                        **video_kwargs,
                        **extra_kwargs,
                    )
                except TypeError as e:
                    last_error = e
                    continue
        raise last_error

    @classmethod
    def _extract_parsed_text(cls, parsed_response) -> str:
        if isinstance(parsed_response, str):
            return parsed_response.strip()
        if isinstance(parsed_response, list):
            parts = [cls._extract_parsed_text(item) for item in parsed_response]
            parts = [part for part in parts if part]
            return '\n'.join(parts).strip()
        if isinstance(parsed_response, dict):
            for key in ('text', 'response', 'answer', 'output', 'content'):
                if key not in parsed_response:
                    continue
                extracted = cls._extract_parsed_text(parsed_response[key])
                if extracted:
                    return extracted
            for value in parsed_response.values():
                extracted = cls._extract_parsed_text(value)
                if extracted:
                    return extracted
        return ''

    def get_model_inputs(self, image_prompt: str, image: Image, crop: bool):
        messages = self._build_messages(image_prompt, image, crop)
        return self._apply_chat_template(messages, image).to(self.device)

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
            gen_kwargs['top_k'] = gen_params.get('top_k', 50)

        generation_start = perf_counter()
        with torch.inference_mode():
            generated_ids = self.model.generate(**model_inputs, **gen_kwargs)
        generation_duration = perf_counter() - generation_start

        generated_ids_trimmed = [
            out_ids[len(in_ids):]
            for in_ids, out_ids in zip(model_inputs.input_ids, generated_ids)
        ]
        raw_console_output = self.processor.batch_decode(
            generated_ids_trimmed,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )[0].strip()

        raw_response = self.processor.decode(
            generated_ids_trimmed[0],
            skip_special_tokens=False,
        ).strip()
        caption = ''
        parse_response = getattr(self.processor, 'parse_response', None)
        if callable(parse_response):
            try:
                parsed_response = parse_response(raw_response)
                caption = self._extract_parsed_text(parsed_response)
            except Exception:
                caption = ''
        if not caption:
            caption = self.processor.batch_decode(
                generated_ids_trimmed,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            )[0].strip()

        if self.caption_start and self.caption_start.strip():
            caption = f'{self.caption_start.strip()} {caption}'

        if '</think>' in caption:
            caption = caption.split('</think>')[-1].strip()
        caption = re.sub(r'^<\|channel\|>thought\s*<\|channel\|>', '', caption).strip()

        if self.remove_tag_separators:
            caption = caption.replace(self.thread.tag_separator, ' ')
        if self.remove_new_lines:
            caption = caption.replace('\n', ' ')
            caption = re.sub(r' +', ' ', caption)

        self.thread.record_generation_metrics(
            self.estimate_output_token_count(caption),
            generation_duration,
        )
        return caption, self.format_console_output(raw_console_output, caption)
