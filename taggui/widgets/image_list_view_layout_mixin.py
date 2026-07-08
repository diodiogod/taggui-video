from widgets.image_list_shared import *  # noqa: F401,F403
from widgets.image_list_masonry_lifecycle_service import MasonryLifecycleService
from widgets.image_list_masonry_completion_service import MasonryCompletionService

class ImageListViewLayoutMixin:
    def _get_masonry_lifecycle_service(self) -> MasonryLifecycleService:
        service = getattr(self, "_masonry_lifecycle_service", None)
        if service is None:
            service = MasonryLifecycleService(self)
            self._masonry_lifecycle_service = service
        return service

    def _check_masonry_completion(self):
        """Check if multiprocessing calculation is complete (non-blocking poll)."""
        self._get_masonry_lifecycle_service().check_masonry_completion()


    def _on_masonry_calculation_progress(self, current, total):
        """Update progress bar during calculation."""
        self._get_masonry_lifecycle_service().on_masonry_calculation_progress(current, total)


    def _get_masonry_completion_service(self) -> MasonryCompletionService:
        service = getattr(self, "_masonry_completion_service", None)
        if service is None:
            service = MasonryCompletionService(self)
            self._masonry_completion_service = service
        return service

    def _on_masonry_calculation_complete(self, result):
        """Called when multiprocessing calculation completes."""
        self._get_masonry_completion_service().on_masonry_calculation_complete(result)


    def _map_row_to_global_index_safely(self, row: int) -> int:
        """Fallback mapping if model lacks the direct method."""
        try:
            model = self.model().sourceModel() if hasattr(self.model(), 'sourceModel') else self.model()
            if not model: return row
        
            if hasattr(model, 'get_global_index_for_row'):
                return model.get_global_index_for_row(row)
        
            # Manual fallback logic if model is busy/reset
            return row # In normal mode row == global index
        except Exception:
            return row


    def _get_masonry_item_rect(self, index):
        """Get QRect for item at given index from masonry results."""
        # Build lookup dict if not exists or stale
        if not hasattr(self, '_masonry_index_map') or self._masonry_index_map is None:
            self._rebuild_masonry_index_map()
    
        # Lookup by global index (not list position!)
        item = self._masonry_index_map.get(index)
        if item:
            width = item.get('width', 0)
            height = item.get('height', 0)
            if width > 0 and height > 0 and width < 100000 and height < 100000:
                return QRect(item['x'], item['y'], width, height)
        return QRect()


    def _rebuild_masonry_index_map(self):
        """Build a dict mapping global index -> item for O(1) lookup."""
        self._masonry_index_map = {}
        if self._masonry_items:
            for item in self._masonry_items:
                self._masonry_index_map[item['index']] = item



    def _get_masonry_visible_items(self, viewport_rect):
        """Get masonry items that intersect with viewport_rect."""
        if not self._masonry_items:
            return []

        viewport_top = viewport_rect.top()
        viewport_bottom = viewport_rect.bottom()

        # Linear search: masonry items are NOT sorted by Y (columns interleave Y values)
        # Binary search was incorrectly assuming sorted order
        visible = []
        for item in self._masonry_items:
            item_y = item['y']
            item_bottom = item_y + item['height']
        
            # Check if item overlaps with viewport vertically
            if item_bottom >= viewport_top and item_y <= viewport_bottom:
                item_rect = QRect(item['x'], item_y, item['width'], item['height'])
                if item_rect.intersects(viewport_rect):
                    visible.append({
                        'index': item['index'],
                        'rect': item_rect
                    })

        # DEBUG: Log when no visible items found at deep scroll
        if not visible and viewport_top > 50000:
            # Find Y range of all items
            if self._masonry_items:
                min_y = min(item['y'] for item in self._masonry_items)
                max_y = max(item['y'] + item['height'] for item in self._masonry_items)
                # print(f"[VISIBLE_DEBUG] viewport={viewport_top}-{viewport_bottom}, items Y range={min_y}-{max_y}, count={len(self._masonry_items)}")

        return visible


    def _get_masonry_total_height(self):
        """Get total height from masonry results."""
        return self._masonry_total_height
