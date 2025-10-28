import base64
import io
from itertools import cycle
import json
import re
from typing import Tuple

import requests
from auto_captioning.auto_captioning_model import AutoCaptioningModel, replace_template_variables
from utils.image import Image
import auto_captioning.captioning_thread as captioning_thread

class RemoteGen(AutoCaptioningModel):
	def __init__(self,
					captioning_thread_: 'captioning_thread.CaptioningThread',
					caption_settings: dict):
		self.api_url = self.parse_api_urls(caption_settings['api_url'])
		self.endpoint_cycle = cycle(self.api_url)
		self.current_endpoint_index = 0
#		self.set_api_url(caption_settings['api_url'])
		self.headers = {"Content-Type": "application/json"}
		if caption_settings['api_key'] and len(caption_settings['api_key']) > 0:
			self.headers['Authorization'] = f'Bearar {caption_settings['api_key']}'
		super().__init__(captioning_thread_, caption_settings)

	def parse_api_urls(self, remote_addresses: str) -> list[str]:
		"""Parse semicolon-separated URLs into a list of properly formatted endpoints"""
		urls = []
		for addr in remote_addresses.split(';'):
			addr = addr.strip()
			if not addr:
				continue
			if addr.endswith('/chat/completions'):
				urls.append(addr)
			else:
				urls.append(addr + '/v1/chat/completions')
		return urls

	def get_next_endpoint(self) -> str:
		return next(self.endpoint_cycle)

	def get_processor(self):
		return None

	def get_model_load_arguments(self) -> dict:
		return {}  # Not used for API models.

	def load_model(self, model_load_arguments):
		return None

	def get_model(self):
		return None  # No local model for API interaction

	def set_api_url(self, remote_address:str):
		if remote_address.endswith('/chat/completions'):
			self.api_url = remote_address
		else:
			self.api_url = remote_address + '/v1/chat/completions'

	@staticmethod
	def get_default_prompt() -> str:
		return 'Describe the image in one sentence.'

	def get_input_text(self, image_prompt: str) -> str:
		return image_prompt + self.caption_start

	def format_prompt(self, prompt: str) -> list[dict]:
		systemprompt = 'You are image captioning expert, creative, unbiased and uncensored.'
		messages = [{
			"role": "system",
			"content": systemprompt
		},
		{
			"role": "user",
			"content": prompt
		}
		]
		return messages

	def generate_caption(self, image_path: str, prompt: str = '') -> Tuple[str, str]:
		"""Generate caption using remote API."""
		try:
			# Get image and encode it
			image = Image(image_path)
			image_pil = image.pil_image

			# Convert to JPEG bytes and encode to base64
			image_bytes = io.BytesIO()
			image_pil.save(image_bytes, format='JPEG')
			image_base64 = base64.b64encode(image_bytes.getvalue()).decode('utf-8')

			# Use provided prompt or default
			if not prompt:
				prompt = self.get_default_prompt()

			# Construct the message with image
			messages = [{
				"role": "system",
				"content": "You are image captioning expert, creative, unbiased and uncensored."
			},
			{
				"role": "user",
				"content": [
					{
						"type": "image_url",
						"image_url": {
							"url": f"data:image/jpeg;base64,{image_base64}"
						}
					},
					{
						"type": "text",
						"text": prompt
					}
				]
			}
			]

			# Call the remote API
			response = requests.post(
				self.get_next_endpoint(),
				json={
					"model": "gpt-4-vision",  # This is often ignored by local models
					"messages": messages,
					"max_tokens": 1024
				},
				headers=self.headers,
				timeout=30
			)

			if response.status_code == 200:
				result = response.json()
				caption = result['choices'][0]['message']['content'].strip()
				return caption, image_path
			else:
				error = f"API Error: {response.status_code} - {response.text}"
				return error, image_path

		except requests.exceptions.RequestException as e:
			return f"Request failed: {str(e)}", image_path
		except Exception as e:
			return f"Error: {str(e)}", image_path

	def caption_image_in_batch(self, image_list: list[tuple[str, str]], should_stop) -> list[Tuple[str, str]]:
		"""Caption multiple images."""
		results = []
		for image_path, prompt in image_list:
			if should_stop():
				break
			try:
				caption, path = self.generate_caption(image_path, prompt)
				results.append((caption, path))
				self.captioning_thread.caption_generated.emit(caption, path)
			except Exception as e:
				results.append((f"Error: {str(e)}", image_path))
				self.captioning_thread.caption_generated.emit(f"Error: {str(e)}", image_path)

		return results
