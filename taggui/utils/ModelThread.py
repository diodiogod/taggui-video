from abc import abstractmethod
from datetime import datetime
from time import perf_counter
import subprocess

import numpy as np
from PIL import UnidentifiedImageError
from transformers import BatchFeature
from PySide6.QtCore import QModelIndex, QThread, Qt, Signal

from utils.image import Image
from models.image_list_model import ImageListModel

def format_duration(seconds: float) -> str:
    seconds_per_minute = 60
    seconds_per_hour = 60 * seconds_per_minute
    seconds_per_day = 24 * seconds_per_hour
    if seconds < seconds_per_minute:
        return f'{seconds:.1f} seconds'
    if seconds < seconds_per_hour:
        minutes = seconds / seconds_per_minute
        return f'{minutes:.1f} minutes'
    if seconds < seconds_per_day:
        hours = seconds / seconds_per_hour
        return f'{hours:.1f} hours'
    days = seconds / seconds_per_day
    return f'{days:.1f} days'


class ModelThread(QThread):
    """Base class for all model running threads"""
    text_outputted = Signal(str)
    clear_console_text_edit_requested = Signal()
    progress_bar_update_requested = Signal(int)

    def __init__(self, parent, image_list_model: ImageListModel,
                 selected_image_indices: list[QModelIndex]):
        super().__init__(parent)
        self.image_list_model = image_list_model
        self.selected_image_indices = selected_image_indices
        self.is_error = False
        self.error_message = ''
        self.is_canceled = False
        self.device = 'default'
        self.text = {
            'Generating': 'Generating',
            'generating': 'generating'
        }
        self.batch_started_at: float | None = None
        self.total_items = 0
        self.completed_items = 0
        self.current_item_index: int | None = None
        self.current_item_name: str | None = None
        self.current_item_started_at: float | None = None
        self.current_stage = 'idle'
        self.total_completed_seconds = 0.0
        self.last_item_duration: float | None = None
        self.last_generation_duration: float | None = None
        self.last_generation_token_count: int | None = None
        self.last_generation_tokens_per_second: float | None = None
        self.external_process: subprocess.Popen | None = None

    def reset_progress_state(self):
        self.batch_started_at = None
        self.total_items = 0
        self.completed_items = 0
        self.current_item_index = None
        self.current_item_name = None
        self.current_item_started_at = None
        self.current_stage = 'idle'
        self.total_completed_seconds = 0.0
        self.last_item_duration = None
        self.last_generation_duration = None
        self.last_generation_token_count = None
        self.last_generation_tokens_per_second = None

    def record_generation_metrics(self, token_count: int | None,
                                  generation_seconds: float | None):
        self.last_generation_duration = generation_seconds
        self.last_generation_token_count = token_count
        if (token_count is not None and generation_seconds is not None
                and generation_seconds > 0):
            self.last_generation_tokens_per_second = (
                float(token_count) / float(generation_seconds))
        else:
            self.last_generation_tokens_per_second = None

    def run_generating(self):
        self.reset_progress_state()
        self.batch_started_at = perf_counter()
        self.total_items = len(self.selected_image_indices)
        self.current_stage = 'loading_model'
        self.clear_console_text_edit_requested.emit()
        self.load_model()
        if self.is_error:
            print(self.error_message)
            self.current_stage = 'error'
            return
        if self.is_canceled:
            print(f"Canceled {self.text['generating']}.")
            self.current_stage = 'canceled'
            return
        selected_image_count = len(self.selected_image_indices)
        are_multiple_images_selected = selected_image_count > 1
        generating_start_datetime = datetime.now()
        generating_message = self.get_generating_message(
            are_multiple_images_selected, generating_start_datetime)
        print(generating_message)
        for i, image_index in enumerate(self.selected_image_indices):
            start_time = perf_counter()
            if self.is_canceled:
                print(f"Canceled {self.text['generating']}.")
                self.current_stage = 'canceled'
                return
            image: Image = self.image_list_model.data(image_index,
                                                      Qt.ItemDataRole.UserRole)
            self.current_item_index = i + 1
            self.current_item_name = image.path.name
            self.current_item_started_at = start_time
            self.current_stage = 'preparing_input'
            try:
                image_prompt, model_inputs = self.get_model_inputs(image)
            except UnidentifiedImageError:
                print(f'Skipping {image.path.name} because its file format is '
                      'not supported or it is a corrupted image.')
            else:
                self.current_stage = 'generating'
                try:
                    console_output_caption = self.generate_output(
                        image_index, image, image_prompt, model_inputs)
                except Exception as exception:
                    partial_console_output = getattr(
                        exception, 'console_output', None)
                    if partial_console_output:
                        print(
                            f'{image.path.name} '
                            f'({perf_counter() - start_time:.1f} s, incomplete):\n'
                            f'{partial_console_output}'
                        )
                    raise
                print(f'{image.path.name} ({perf_counter() - start_time:.1f} s):\n'
                      f'{console_output_caption}')
            finally:
                item_duration = perf_counter() - start_time
                self.completed_items = i + 1
                self.last_item_duration = item_duration
                self.total_completed_seconds += item_duration
                if are_multiple_images_selected:
                    self.progress_bar_update_requested.emit(self.completed_items)
                self.current_item_name = None
                self.current_item_started_at = None
                self.current_item_index = None
                self.current_stage = 'idle'
        if are_multiple_images_selected:
            generating_end_datetime = datetime.now()
            total_generating_duration = ((generating_end_datetime
                                          - generating_start_datetime)
                                         .total_seconds())
            average_generating_duration = (total_generating_duration /
                                           selected_image_count)
            print(
                f"Finished {self.text['generating']} {selected_image_count} "
                f'images in {format_duration(total_generating_duration)} '
                f'({average_generating_duration:.1f} s/image) at '
                f'{generating_end_datetime.strftime("%Y-%m-%d %H:%M:%S")}.'
            )
        self.current_stage = 'finished'

    @abstractmethod
    def load_model(self):
        """Load the model for the generating task."""
        pass

    def get_generating_message(self, are_multiple_images_selected: bool,
                               generating_start_datetime: datetime) -> str:
        if are_multiple_images_selected:
            generating_start_datetime_string = (
                generating_start_datetime.strftime('%Y-%m-%d %H:%M:%S'))
            return (
                f"{self.text['Generating']}... (device: {self.device}, "
                f'start time: {generating_start_datetime_string})'
            )
        return f"{self.text['Generating']}... (device: {self.device})"

    @abstractmethod
    def get_model_inputs(self, image: Image) -> tuple[
        str | None, BatchFeature | dict | np.ndarray]:
        pass

    @abstractmethod
    def generate_output(self, image_index,
                        image: Image,
                        image_prompt: str | None,
                        model_inputs: BatchFeature | dict | np.ndarray) -> str:
        pass

    def run(self):
        try:
            self.run_generating()
        except Exception as exception:
            self.is_error = True
            # Show the error message in the console text edit.
            raise exception

    def write(self, text: str):
        self.text_outputted.emit(text)

    def set_external_process(self, process: subprocess.Popen | None):
        self.external_process = process

    def clear_external_process(self, process: subprocess.Popen | None = None):
        if process is None or self.external_process is process:
            self.external_process = None

    def cancel_external_process(self):
        process = self.external_process
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
        except Exception:
            pass
        finally:
            if self.external_process is process:
                self.external_process = None

    def request_cancel(self):
        self.is_canceled = True
        self.cancel_external_process()
