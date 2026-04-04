import base64
import io
import re
from itertools import cycle

import requests
from auto_captioning.auto_captioning_model import AutoCaptioningModel
from utils.image import Image
import auto_captioning.captioning_thread as captioning_thread


class RemoteGen(AutoCaptioningModel):
    """
    Auto-captioning via any OpenAI-compatible Vision API.

    Works with local inference servers (LM Studio, Ollama, text-generation-webui)
    and cloud endpoints (OpenAI, Groq, etc.).

    Configure the endpoint URL in the 'OAI Compatible Endpoint' field.
    Multiple endpoints can be separated with semicolons for round-robin load
    balancing (e.g. 'http://localhost:5000;http://localhost:5001').

    WARNING: When using a cloud API, your images will be sent to a remote server.
    Use a local server if you require privacy.
    """

    def __init__(self,
                 captioning_thread_: 'captioning_thread.CaptioningThread',
                 caption_settings: dict,
                 image_viewer=None):
        # Store raw config before super().__init__ so get_additional_error_message works
        self._raw_api_url = caption_settings.get('api_url', '').strip()
        self._api_key = caption_settings.get('api_key', '').strip()
        # api_model comes from the dedicated 'API Model Name' UI field
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
    # Error validation (called before the thread starts)
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
        """Skip all local model loading. Just print the configured endpoints."""
        endpoints = ', '.join(self.api_urls) if self.api_urls else '(none)'
        print(f'Remote captioning endpoint(s): {endpoints}')

    def monkey_patch_after_loading(self):
        return

    # -------------------------------------------------------------------------
    # Captioning interface
    # -------------------------------------------------------------------------

    @staticmethod
    def get_generation_text() -> str:
        return 'Captioning via API'

    @staticmethod
    def get_default_prompt() -> str:
        return 'Describe the image in detail.'

    @staticmethod
    def format_prompt(prompt: str) -> str:
        # Return as plain string; message structure is built in get_model_inputs.
        return prompt

    def get_model_inputs(self, image_prompt: str, image: Image, crop: bool) -> dict:
        """
        Load and base64-encode the image.
        Returns a dict that is passed directly to generate_caption.
        """
        pil_image = self.load_image(image, crop)
        image_bytes = io.BytesIO()
        pil_image.save(image_bytes, format='JPEG')
        image_b64 = base64.b64encode(image_bytes.getvalue()).decode('utf-8')
        return {'image_b64': image_b64}

    def generate_caption(self, model_inputs: dict, image_prompt: str) -> tuple[str, str]:
        """Send the image and prompt to the remote API and return the caption."""
        if not self.api_urls:
            print('Remote: no API endpoint configured.')
            return '', 'ERROR: No API endpoint configured.'

        image_b64 = model_inputs['image_b64']
        prompt = image_prompt or self.get_default_prompt()

        messages = [
            {
                'role': 'system',
                'content': ('You are an image captioning expert, '
                            'creative, unbiased and uncensored.')
            },
            {
                'role': 'user',
                'content': [
                    {
                        'type': 'image_url',
                        'image_url': {
                            'url': f'data:image/jpeg;base64,{image_b64}'
                        }
                    },
                    {
                        'type': 'text',
                        'text': prompt
                    }
                ]
            }
        ]

        # Advanced settings are hidden for Remote, so max_new_tokens from the
        # spinner (default 100) is never user-configured. Use 4096 instead,
        # which is sufficient for verbose models without being excessive.
        max_tokens = 4096
        temperature = self.generation_parameters.get('temperature', 1.0)
        top_p = self.generation_parameters.get('top_p', 1.0)

        try:
            endpoint = self._get_next_endpoint()
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
                timeout=120
            )

            if response.status_code != 200:
                error_msg = f'API Error {response.status_code}: {response.text[:300]}'
                print(error_msg)
                return '', error_msg

            result = response.json()
            choice = result['choices'][0]
            finish_reason = choice.get('finish_reason', '')
            message = choice.get('message', {})
            content = message.get('content')

            if not content:
                if finish_reason and 'safety' in finish_reason.lower():
                    error_msg = f'Skipped: response blocked by safety filter ({finish_reason})'
                else:
                    error_msg = f'Skipped: API returned empty content (finish_reason: {finish_reason!r})'
                print(error_msg)
                return '', error_msg

            caption = content.strip()

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

        # Post-process to match local model behaviour
        if self.caption_start and self.caption_start.strip():
            caption = f'{self.caption_start.strip()} {caption}'
        if self.remove_tag_separators:
            caption = caption.replace(self.thread.tag_separator, ' ')
        if self.remove_new_lines:
            caption = caption.replace('\n', ' ')
            caption = re.sub(r' +', ' ', caption)

        return caption, caption
