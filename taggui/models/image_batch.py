from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

from PySide6.QtCore import Qt

from utils.image import Image
from utils.image_index_db import ImageIndexDB

if TYPE_CHECKING:
    from models.image_list_model import ImageListModel


@dataclass(frozen=True)
class ImageBatchItem:
    """Stable batch reference for an image that may not be loaded in the view."""

    image: Image

    def data(self, role=Qt.ItemDataRole.UserRole):
        if role == Qt.ItemDataRole.UserRole:
            return self.image
        return None


@dataclass(frozen=True)
class PaginatedImageBatch:
    """Repeatable snapshot of the current paginated/filtered image domain."""

    model: "ImageListModel"
    directory_path: Path
    count: int
    sort_field: str
    sort_dir: str
    filter_sql: str
    filter_bindings: tuple
    random_seed: int
    selection_mode: str = 'all_except'
    selection_paths: tuple[str, ...] = ()
    chunk_size: int = 500

    def __len__(self) -> int:
        return max(0, int(self.count))

    def __iter__(self) -> Iterator[ImageBatchItem]:
        database = ImageIndexDB(self.directory_path)
        try:
            image_ids = database.get_ordered_image_ids(
                sort_field=self.sort_field,
                sort_dir=self.sort_dir,
                filter_sql=self.filter_sql,
                bindings=self.filter_bindings,
                random_seed=self.random_seed,
            )
            if self.selection_paths:
                selected_ids = set(
                    database.get_image_ids_for_paths(self.selection_paths).values()
                )
                if self.selection_mode == 'only':
                    image_ids = [
                        image_id for image_id in image_ids
                        if image_id in selected_ids
                    ]
                else:
                    image_ids = [
                        image_id for image_id in image_ids
                        if image_id not in selected_ids
                    ]
            elif self.selection_mode == 'only':
                image_ids = []
            chunk_size = max(1, int(self.chunk_size))
            for offset in range(0, len(image_ids), chunk_size):
                chunk = image_ids[offset:offset + chunk_size]
                images, _missing_paths = self.model._load_images_from_db_ids(
                    chunk,
                    db=database,
                    directory_path=self.directory_path,
                )
                for image in images:
                    yield ImageBatchItem(image)
        finally:
            database.close()
