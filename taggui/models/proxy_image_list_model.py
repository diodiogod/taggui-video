import operator
import re
from typing import List, Dict, Any, Optional
from fnmatch import fnmatchcase

from PySide6.QtCore import (QModelIndex, QSortFilterProxyModel, Qt, QRect,
                            QSize, Signal)
from transformers import PreTrainedTokenizerBase

from models.image_list_model import ImageListModel
from utils.image import Image
import utils.target_dimension as target_dimension

comparison_operators = {
    '=': operator.eq,
    '==': operator.eq,
    '!=': operator.ne,
    '<': operator.lt,
    '>': operator.gt,
    '<=': operator.le,
    '>=': operator.ge
}


class ProxyImageListModel(QSortFilterProxyModel):
    filter_changed = Signal()
    pages_updated = Signal(list)  # Forward from source model for buffered mode

    def __init__(self, image_list_model: ImageListModel,
                 tokenizer: PreTrainedTokenizerBase, tag_separator: str):
        super().__init__()
        self.setSourceModel(image_list_model)
        self.tokenizer = tokenizer
        self.tag_separator = tag_separator
        self.filter: list | None = None
        self._media_type_filter = 'All'
        self._confidence_pattern = re.compile(r'^(<=|>=|==|<|>|=)\s*(0?[.,][0-9]+)')
        image_list_model.pages_updated.connect(self._on_source_pages_updated)

    def _on_source_pages_updated(self, pages):
        """Handle page updates from source model in buffered mode."""
        # NOTE: invalidate()/invalidateFilter() on buffered page updates has caused
        # native Qt access violations on Windows in this code path.
        # Forward only; view logic already consumes source pages directly.
        self.pages_updated.emit(list(pages) if pages else [])

    def get_filtered_aspect_ratios(self) -> list[tuple[int, float]]:
        """Get (row, aspect_ratio) pairs for filtered items without iterating Qt model.

        Returns list of (proxy_row, aspect_ratio) tuples. This is MUCH faster than
        calling .index() and .data() in a loop on the UI thread.

        In paginated mode with buffered masonry, returns only loaded pages.
        """
        source_model = self.sourceModel()
        if not source_model:
            return []

        # Check if using buffered masonry (paginated mode)
        if hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:
            # Buffered masonry: get only loaded pages
            items_data, first_idx, last_idx = source_model.get_buffered_aspect_ratios()

            # items_data is [(global_idx, aspect_ratio), ...]
            # But we need [(row, aspect_ratio), ...] where row is the index in the loaded items list
            # Since source rowCount() returns only loaded items, row 0 = first loaded item

            # Since source model now handles filtering via SQL in paginated mode,
            # items_data already reflects the filtered dataset.
            # We must NOT re-filter here (avoids mismatches).
            return items_data
        else:
            # Normal mode: get all aspect ratios
            all_aspect_ratios = source_model.get_aspect_ratios()

            # Build filtered list by mapping proxy rows to source rows
            result = []
            for proxy_row in range(self.rowCount()):
                proxy_index = self.index(proxy_row, 0)
                source_index = self.mapToSource(proxy_index)
                if source_index.isValid():
                    source_row = source_index.row()
                    if source_row < len(all_aspect_ratios):
                        result.append((proxy_row, all_aspect_ratios[source_row]))

            return result

    def set_media_type_filter(self, media_type: str):
        """Set media type filter ('All', 'Images', or 'Videos')."""
        if media_type == self._media_type_filter:
            return
        self._media_type_filter = media_type

        # In paginated mode, delegate to source model (applied via SQL in set_filter)
        source_model = self.sourceModel()
        if source_model and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:
            if hasattr(source_model, 'set_media_type_filter'):
                source_model.set_media_type_filter(media_type)
            return

        # Normal mode: invalidate to re-run filterAcceptsRow
        self.invalidateFilter()
        self.filter_changed.emit()

    def set_filter(self, new_filter: list | None):
        self.filter = new_filter
        
        # Check source model capabilities
        source_model = self.sourceModel()
        
        # Delegate SQL filtering to source model in paginated mode
        if source_model and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:
            if hasattr(source_model, 'apply_filter'):
                source_model.apply_filter(new_filter)
                self.filter_changed.emit()
                return

        # Suppress enrichment signals while filtering to prevent layout issues
        if source_model and hasattr(source_model, '_suppress_enrichment_signals'):
            # Enable suppression if filter is active, disable if cleared
            source_model._suppress_enrichment_signals = (new_filter is not None)
            if new_filter:
                print("[FILTER] Suppressing enrichment layout updates during filtering")
            else:
                print("[FILTER] Re-enabling enrichment layout updates")

        self.invalidateFilter()
        self.filter_changed.emit()

    def does_image_match_filter(self, image: Image,
                                filter_: list | str | None) -> bool:
        if filter_ is None:
            return True
        if isinstance(filter_, str):
            return (fnmatchcase(self.tag_separator.join(image.tags),
                                f'*{filter_}*')
                    or fnmatchcase(str(image.path), f'*{filter_}*'))
        if len(filter_) == 1:
            return self.does_image_match_filter(image, filter_[0])
        if len(filter_) == 2:
            if filter_[0] == 'NOT':
                return not self.does_image_match_filter(image, filter_[1])
            if filter_[0] == 'tag':
                return any(fnmatchcase(tag, filter_[1]) for tag in image.tags)
            if filter_[0] == 'caption':
                caption = self.tag_separator.join(image.tags)
                return fnmatchcase(caption, f'*{filter_[1]}*')
            if filter_[0] == 'marking':
                last_colon_index = filter_[1].rfind(':')
                if last_colon_index < 0:
                    return any(fnmatchcase(marking.label, filter_[1])
                               for marking in image.markings)
                else:
                    label = filter_[1][:last_colon_index]
                    confidence = filter_[1][last_colon_index + 1:]
                    match = self._confidence_pattern.match(confidence)
                    if not match or len(match.group(2)) == 0:
                        return False
                    comparison_operator = comparison_operators[match.group(1)]
                    confidence_target = float(match.group(2).replace(',', '.'))
                    return any((fnmatchcase(marking.label, label) and
                               comparison_operator(marking.confidence,
                                                   confidence_target))
                               for marking in image.markings)
            if filter_[0] == 'crops':
                crop = image.crop if image.crop is not None else QRect(0, 0, *image.dimensions)
                return any(fnmatchcase(marking.label, filter_[1]) and
                           marking.rect.intersects(crop) and not crop.contains(marking.rect)
                           for marking in image.markings)
            if filter_[0] == 'visible':
                crop = image.crop if image.crop is not None else QRect(0, 0, *image.dimensions)
                return any(fnmatchcase(marking.label, filter_[1]) and
                           marking.rect.intersects(crop)
                           for marking in image.markings)
            if filter_[0] == 'name':
                return fnmatchcase(image.path.name, f'*{filter_[1]}*')
            if filter_[0] == 'path':
                return fnmatchcase(str(image.path), f'*{filter_[1]}*')
            if filter_[0] == 'size':
                # accept any dimension separator of [x:]
                dimension = (filter_[1]).replace(':', 'x').split('x')
                return (len(dimension) == 2
                        and dimension[0] == str(image.dimensions[0])
                        and dimension[1] == str(image.dimensions[1]))
            if filter_[0] == 'target':
                # accept any dimension separator of [x:]
                dimension = (filter_[1]).replace(':', 'x').split('x')
                if image.target_dimension is None:
                    image.target_dimension = target_dimension.get(QSize(*image.dimensions))
                return (len(dimension) == 2
                        and dimension[0] == str(image.target_dimension.width())
                        and dimension[1] == str(image.target_dimension.height()))
        if filter_[1] == 'AND':
            if len(filter_) < 3:
                return self.does_image_match_filter(image, filter_[0])
            return (self.does_image_match_filter(image, filter_[0])
                    and self.does_image_match_filter(image, filter_[2:]))
        if filter_[1] == 'OR':
            if len(filter_) < 3:
                return self.does_image_match_filter(image, filter_[0])
            return (self.does_image_match_filter(image, filter_[0])
                    or self.does_image_match_filter(image, filter_[2:]))
        comparison_operator = comparison_operators[filter_[1]]
        number_to_compare = None
        if filter_[0] == 'tags':
            number_to_compare = len(image.tags)
        elif filter_[0] == 'chars':
            caption = self.tag_separator.join(image.tags)
            number_to_compare = len(caption)
        elif filter_[0] == 'tokens':
            caption = self.tag_separator.join(image.tags)
            # Subtract 2 for the `<|startoftext|>` and `<|endoftext|>` tokens.
            number_to_compare = len(self.tokenizer(caption).input_ids) - 2
        elif filter_[0] == 'stars':
            number_to_compare = image.rating * 5.0
        elif filter_[0] == 'width':
            number_to_compare = image.dimensions[0]
        elif filter_[0] == 'height':
            number_to_compare = image.dimensions[1]
        elif filter_[0] == 'area':
            number_to_compare =  image.dimensions[0] * image.dimensions[1]
        return comparison_operator(number_to_compare, int(filter_[2]))

    def filterAcceptsRow(self, source_row: int,
                         source_parent: QModelIndex) -> bool:
        # In Paginated Mode, source already filters via SQL.
        source_model = self.sourceModel()
        if source_model and hasattr(source_model, '_paginated_mode') and source_model._paginated_mode:
             return True

        # Show all images when there is no filter and no media type filter.
        if self.filter is None and self._media_type_filter == 'All':
            return True

        image_index = self.sourceModel().index(source_row, 0)
        image: Image = self.sourceModel().data(image_index,
                                               Qt.ItemDataRole.UserRole)

        # Accept unloaded images (None) to avoid hiding them.
        if image is None:
            return True

        # Check media type filter
        if self._media_type_filter == 'Images' and image.is_video:
            return False
        if self._media_type_filter == 'Videos' and not image.is_video:
            return False

        return self.does_image_match_filter(image, self.filter)

    def is_image_in_filtered_images(self, image: Image) -> bool:
        if self._media_type_filter == 'Images' and image.is_video:
            return False
        if self._media_type_filter == 'Videos' and not image.is_video:
            return False
        return (self.filter is None
                or self.does_image_match_filter(image, self.filter))

    def get_list(self) -> list[Image]:
        """Get filtered image list, skipping None entries (unloaded pages in pagination mode)."""
        images = []
        for row in range(self.rowCount()):
            image = self.data(self.index(row, 0, QModelIndex()), Qt.UserRole)
            if image is not None:
                images.append(image)
        return images

    def get_all_aspect_ratios(self) -> list[float]:
        """Pass-through to source model."""
        source = self.sourceModel()
        if hasattr(source, 'get_all_aspect_ratios'):
            return source.get_all_aspect_ratios()
        return []
