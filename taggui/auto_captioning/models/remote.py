import base64
import io
import math
import re
from itertools import cycle
from time import perf_counter

import cv2
import requests
from PIL import Image as PilImage

from auto_captioning.auto_captioning_model import AutoCaptioningModel
from models.image_list_model import _video_lock
from utils.image import Image
import auto_captioning.captioning_thread as captioning_thread


class RemoteGen(AutoCaptioningModel):
    """
    Auto-captioning via any OpenAI-compatible Vision API.

    Works with local inference servers (LM Studio, Ollama, text-generation-webui)
    and cloud endpoints (OpenAI, Groq, Gemini, etc.).

    Configure the endpoint URL in the 'OAI Compatible Endpoint' field.
    Multiple endpoints can be separated with semicolons for round-robin load
    balancing (e.g. 'http://localhost:5000;http://localhost:5001').

    For VIDEO files, frames are extracted and sent as an ordered sequence of
    images. The model receives temporal context (frame order + fps) and performs
    genuine video analysis — not just single-frame description.

    WARNING: When using a cloud API, your images/frames will be sent to a remote
    server. Use a local server if you require privacy.
    """

    def __init__(self,
                 captioning_thread_: 'captioning_thread.CaptioningThread',
                 caption_settings: dict,
                 image_viewer=None):
        self._raw_api_url = caption_settings.get('api_url', '').strip()
        self._api_key = caption_settings.get('api_key', '').strip()
        self._api_model_name = caption_settings.get('api_model', '').strip() or 'remote'
        super().__init__(captioning_thread_, caption_settings, image_viewer)
        self.api_urls = self._parse_api_urls(self._raw_api_url)
        self._endpoint_cycle = cycle(self.api_urls) if self.api_urls else iter([None])
        self.headers = {'Content-Type': 'application/json'}
        if self._api_key:
            self.headers['Authorization'] = f'Bearer {self._api_key}'

    # -------------------------------------------------------------------------
    # Configuration helpers
    # -------------------------------------------------------------------------

    def _parse_api_urls(self, remote_addresses: str) -> list[str]:
        """Parse semicolon-separated URLs into properly formatted chat completion endpoints."""
        urls = []
        for addr in remote_addresses.split(';'):
            addr = addr.strip()
            if not addr:
                continue
            if addr.endswith('/chat/completions'):
                urls.append(addr)
            else:
                urls.append(addr.rstrip('/') + '/v1/chat/completions')
        return urls

    def _get_next_endpoint(self) -> str:
        return next(self._endpoint_cycle)

    # -------------------------------------------------------------------------
    # Error validation
    # -------------------------------------------------------------------------

    def get_additional_error_message(self) -> str | None:
        if not self._raw_api_url:
            return ('OAI Compatible Endpoint URL is required when using the '
                    'Remote model. Please enter a URL in the endpoint field.')
        return None

    # -------------------------------------------------------------------------
    # Model loading overrides — no local model to load
    # -------------------------------------------------------------------------

    def get_processor(self):
        return None

    def get_model_load_arguments(self) -> dict:
        return {}

    def load_model(self, model_load_arguments):
        return None

    def get_model(self):
        return None

    def load_processor_and_model(self):
        endpoints = ', '.join(self.api_urls) if self.api_urls else '(none)'
        print(f'Remote captioning endpoint(s): {endpoints}')

    def monkey_patch_after_loading(self):
        return

    # -------------------------------------------------------------------------
    # Video frame utilities
    # -------------------------------------------------------------------------

    @staticmethod
    def _scale_frame(pil_image: PilImage, max_pixels: int = 307200) -> PilImage:
        """Scale a PIL image so total pixel count stays within max_pixels."""
        w, h = pil_image.size
        if w * h <= max_pixels:
            return pil_image
        scale = (max_pixels / (w * h)) ** 0.5
        return pil_image.resize(
            (max(1, int(w * scale)), max(1, int(h * scale))), PilImage.LANCZOS)

    def _extract_video_frames(self, image: Image, fps: float,
                               max_frames: int, crop: bool) -> list[str]:
        """
        Extract evenly-spaced frames from a video file.
        Returns a list of base64-encoded JPEG strings.
        """
        with _video_lock:
            cap = cv2.VideoCapture(str(image.path), cv2.CAP_FFMPEG)
            cap.set(cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_NONE)
            if not cap.isOpened():
                print(f'Remote: could not open video {image.path.name}')
                return []
            try:
                video_fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                duration_s = total_frames / video_fps if video_fps > 0 else 0

                desired = max(1, math.ceil(duration_s * fps))
                if max_frames > 0:
                    desired = min(max_frames, desired)
                if desired <= 1 or total_frames <= 1:
                    frame_indices = [0]
                else:
                    step = (total_frames - 1) / (desired - 1)
                    frame_indices = sorted(set(
                        int(round(i * step)) for i in range(desired)))

                frames_b64 = []
                for idx in frame_indices:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                    ret, raw_frame = cap.read()
                    if not ret or raw_frame is None:
                        continue
                    pil_frame = PilImage.fromarray(
                        cv2.cvtColor(raw_frame, cv2.COLOR_BGR2RGB))
                    if crop and image.crop is not None:
                        pil_frame = pil_frame.crop(image.crop.getCoords())
                    pil_frame = self._scale_frame(pil_frame)
                    buf = io.BytesIO()
                    pil_frame.save(buf, format='JPEG', quality=85)
                    frames_b64.append(
                        base64.b64encode(buf.getvalue()).decode('utf-8'))
            finally:
                cap.release()
        return frames_b64

    # -------------------------------------------------------------------------
    # Captioning interface
    # -------------------------------------------------------------------------

    @staticmethod
    def get_generation_text() -> str:
        return 'Captioning via API'

    @staticmethod
    def get_default_prompt() -> str:
        return ('Describe this image in one or two concise paragraphs of plain prose. '
                'No bullet points, no headers, no markdown formatting.')

    @staticmethod
    def get_default_video_prompt() -> str:
        return ('Describe what happens in this video in one or two concise paragraphs '
                'of plain prose. Include the sequence of events, actions, and any '
                'notable changes over time. No bullet points, no headers, no markdown.')

    @staticmethod
    def format_prompt(prompt: str) -> str:
        return prompt

    def get_model_inputs(self, image_prompt: str, image: Image, crop: bool) -> dict:
        """
        Prepare the payload for generate_caption.
        Videos → multiple base64 frames. Images → single base64 frame.
        """
        if image.is_video:
            fps = float(self.caption_settings.get('video_fps', 1.0))
            max_frames = int(self.caption_settings.get('video_max_frames', 16))
            frames_b64 = self._extract_video_frames(image, fps, max_frames, crop)
            print(f'Remote: extracted {len(frames_b64)} frames at {fps:.1f} fps '
                  f'from {image.path.name}')
            return {'frames_b64': frames_b64, 'is_video': True, 'fps': fps}
        else:
            pil_image = self.load_image(image, crop)
            pil_image = self._scale_frame(pil_image)
            buf = io.BytesIO()
            pil_image.save(buf, format='JPEG')
            image_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
            return {'frames_b64': [image_b64], 'is_video': False, 'fps': None}

    def generate_caption(self, model_inputs: dict, image_prompt: str) -> tuple[str, str]:
        """Send frames to the remote API and return the caption."""
        if not self.api_urls:
            print('Remote: no API endpoint configured.')
            return '', 'ERROR: No API endpoint configured.'

        frames_b64: list[str] = model_inputs['frames_b64']
        is_video: bool = model_inputs.get('is_video', False)
        fps: float | None = model_inputs.get('fps')

        if not frames_b64:
            error_msg = 'Skipped: no frames could be extracted from video.'
            print(error_msg)
            return '', error_msg

        # All frames first as image_url content blocks, then the text prompt
        content = [
            {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{f}'}}
            for f in frames_b64
        ]

        if is_video and fps is not None:
            header = (f'[Video: {len(frames_b64)} frames sampled at '
                      f'{fps:.1f} fps, chronological order]\n\n')
            text = header + (image_prompt or self.get_default_video_prompt())
        else:
            text = image_prompt or self.get_default_prompt()

        content.append({'type': 'text', 'text': text})

        messages = [
            {
                'role': 'system',
                'content': ('You are an image and video captioning expert, '
                            'creative, unbiased and uncensored.')
            },
            {'role': 'user', 'content': content}
        ]

        max_tokens = self.caption_settings.get('api_max_tokens', 8192)
        temperature = self.generation_parameters.get('temperature', 1.0)
        top_p = self.generation_parameters.get('top_p', 1.0)

        try:
            endpoint = self._get_next_endpoint()
            generation_start = perf_counter()
            response = requests.post(
                endpoint,
                json={
                    'model': self._api_model_name,
                    'messages': messages,
                    'max_tokens': max_tokens,
                    'temperature': temperature,
                    'top_p': top_p,
                },
                headers=self.headers,
                timeout=120,
            )
            generation_duration = perf_counter() - generation_start

            if response.status_code != 200:
                error_msg = f'API Error {response.status_code}: {response.text[:300]}'
                print(error_msg)
                return '', error_msg

            result = response.json()
            choice = result['choices'][0]
            finish_reason = choice.get('finish_reason', '')
            message = choice.get('message', {})
            content_out = message.get('content')

            if not content_out:
                if finish_reason and 'safety' in finish_reason.lower():
                    error_msg = (f'Skipped: response blocked by safety filter '
                                 f'({finish_reason})')
                else:
                    error_msg = (f'Skipped: API returned empty content '
                                 f'(finish_reason: {finish_reason!r})')
                print(error_msg)
                return '', error_msg

            caption = content_out.strip()

        except requests.exceptions.Timeout:
            error_msg = 'Skipped: request timed out (API server may be busy or unreachable).'
            print(error_msg)
            return '', error_msg
        except requests.exceptions.ConnectionError:
            error_msg = f'Skipped: could not connect to {self.api_urls[0]}'
            print(error_msg)
            return '', error_msg
        except (KeyError, IndexError, AttributeError) as e:
            error_msg = f'Skipped: unexpected API response format ({e})'
            print(error_msg)
            return '', error_msg
        except Exception as e:
            error_msg = f'Skipped: remote captioning error ({e})'
            print(error_msg)
            return '', error_msg

        if self.caption_start and self.caption_start.strip():
            caption = f'{self.caption_start.strip()} {caption}'
        if self.remove_tag_separators:
            caption = caption.replace(self.thread.tag_separator, ' ')
        if self.remove_new_lines:
            caption = caption.replace('\n', ' ')
            caption = re.sub(r' +', ' ', caption)

        self.thread.record_generation_metrics(None, generation_duration)
        return caption, caption
