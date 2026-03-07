from PySide6.QtCore import QModelIndex, QThread, Signal, Qt

from PIL import Image as PILImage
import pillow_jxl

import torch
from ultralytics import YOLO

from models.image_list_model import ImageListModel
from utils.image import Image
from utils.ModelThread import ModelThread


class MarkingThread(ModelThread):
    # The image index, the caption, and the tags with the caption added. The
    # third parameter must be declared as `list` instead of `list[str]` for it
    # to work.
    marking_generated = Signal(QModelIndex, list)
    marking_result = Signal(str, int)

    def __init__(self, parent, image_list_model: ImageListModel,
                 selected_image_indices: list[QModelIndex],
                 marking_settings: dict):
        super().__init__(parent, image_list_model, selected_image_indices)
        self.marking_settings = marking_settings
        self.model: YOLO | None = None
        self.text = {
            'Generating': 'Marking',
            'generating': 'marking'
        }

    @staticmethod
    def _intersection_area(box_a: list[float], box_b: list[float]) -> float:
        x1 = max(float(box_a[0]), float(box_b[0]))
        y1 = max(float(box_a[1]), float(box_b[1]))
        x2 = min(float(box_a[2]), float(box_b[2]))
        y2 = min(float(box_a[3]), float(box_b[3]))
        if x2 <= x1 or y2 <= y1:
            return 0.0
        return (x2 - x1) * (y2 - y1)

    @classmethod
    def _box_area(cls, box: list[float]) -> float:
        width = max(0.0, float(box[2]) - float(box[0]))
        height = max(0.0, float(box[3]) - float(box[1]))
        return width * height

    @classmethod
    def _overlap_score(cls, box_a: list[float], box_b: list[float]) -> float:
        intersection = cls._intersection_area(box_a, box_b)
        if intersection <= 0.0:
            return 0.0
        area_a = cls._box_area(box_a)
        area_b = cls._box_area(box_b)
        if area_a <= 0.0 or area_b <= 0.0:
            return 0.0
        union = area_a + area_b - intersection
        iou = (intersection / union) if union > 0.0 else 0.0
        smaller_overlap = intersection / min(area_a, area_b)
        return max(iou, smaller_overlap)

    @classmethod
    def _merge_marking_group(cls, group: list[dict]) -> dict:
        merged = dict(group[0])
        merged['box'] = [
            min(float(item['box'][0]) for item in group),
            min(float(item['box'][1]) for item in group),
            max(float(item['box'][2]) for item in group),
            max(float(item['box'][3]) for item in group),
        ]
        merged['confidence'] = round(
            max(float(item.get('confidence', 0.0) or 0.0) for item in group),
            3,
        )
        return merged

    @classmethod
    def _merge_overlapping_markings(cls, markings: list[dict], threshold: float) -> list[dict]:
        if len(markings) < 2:
            return markings

        threshold = max(0.0, min(float(threshold), 1.0))
        merged_markings: list[dict] = []
        remaining = list(markings)

        while remaining:
            seed = remaining.pop(0)
            group = [seed]
            changed = True
            while changed:
                changed = False
                next_remaining = []
                for candidate in remaining:
                    same_class = (
                        candidate.get('label') == seed.get('label')
                        and candidate.get('type') == seed.get('type')
                    )
                    if same_class and any(
                        cls._overlap_score(member['box'], candidate['box']) >= threshold
                        for member in group
                    ):
                        group.append(candidate)
                        changed = True
                    else:
                        next_remaining.append(candidate)
                remaining = next_remaining
            merged_markings.append(cls._merge_marking_group(group))

        return merged_markings

    def load_model(self):
        if not self.model:
            self.error_message = 'Model not preloaded.'
            self.is_error = True
        pass

    def preload_model(self):
        if self.marking_settings['model_path'] is None:
            self.error_message = 'Model path not set'
            self.is_error = True
            self.model = None
            return
        self.model = YOLO(self.marking_settings['model_path'])
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'

    def _predict_with_device(self, pil_image, device: str):
        return self.model.predict(source=pil_image,
                                  conf=self.marking_settings['conf'],
                                  iou=self.marking_settings['iou'],
                                  max_det=self.marking_settings['max_det'],
                                  classes=list(self.marking_settings['classes'].keys()),
                                  retina_masks=True,
                                  device=device)

    def get_model_inputs(self, image: Image):
        return '', {}

    def generate_output(self, image_index, image: Image, image_prompt, model_inputs) -> str:
        if len(self.marking_settings['classes']) == 0:
            return 'No classes to mark selected.'
        pil_image = PILImage.open(image.path)
        try:
            results = self._predict_with_device(pil_image, self.device)
        except NotImplementedError as exc:
            # Some local environments ship CUDA-enabled torch with CPU-only
            # torchvision, which makes Ultralytics fail in NMS on CUDA.
            # Fall back to CPU transparently so auto-marking still works.
            message = str(exc)
            if self.device != 'cpu' and 'torchvision::nms' in message and 'CUDA' in message:
                self.device = 'cpu'
                results = self._predict_with_device(pil_image, self.device)
            else:
                raise
        markings = []
        for r in results:
            for box, class_id, confidence in zip(r.boxes.xyxy.to('cpu').tolist(),
                                                 r.boxes.cls.to('cpu').tolist(),
                                                 r.boxes.conf.to('cpu').tolist()):
                marking = self.marking_settings['classes'].get(class_id)
                if marking is not None:
                    markings.append({'box': box,
                                     'label': marking[0],
                                     'type': marking[1],
                                     'confidence': round(confidence, 3)})
        if self.marking_settings.get('merge_overlaps'):
            markings = self._merge_overlapping_markings(
                markings,
                self.marking_settings.get('merge_overlap_threshold', 0.6),
            )
        self.marking_generated.emit(image_index, markings)
        self.marking_result.emit(image.path.name, len(markings))
        return f'Found {len(markings)} marking(s).'
