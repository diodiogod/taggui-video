from widgets.image_list_shared import *  # noqa: F401,F403
from widgets.image_list_masonry_lifecycle_service import MasonryLifecycleService

class ImageListViewRecalcMixin:
    def _get_masonry_lifecycle_service(self) -> MasonryLifecycleService:
        service = getattr(self, "_masonry_lifecycle_service", None)
        if service is None:
            service = MasonryLifecycleService(self)
            self._masonry_lifecycle_service = service
        return service

    def _do_recalculate_masonry(self):
        """Actually perform the masonry recalculation (called after debounce)."""
        self._get_masonry_lifecycle_service().do_recalculate_masonry()
