"""Navigate a prompt window using its originating media model and viewer."""

from pathlib import Path
import time

from PySide6.QtCore import QModelIndex, QObject, QPersistentModelIndex, QTimer, Qt, Signal
from shiboken6 import isValid


class PromptNavigator(QObject):
    changed = Signal()
    navigated = Signal(object)
    failed = Signal(str)

    def __init__(self, path, *, list_view=None, viewer=None, index=None, parent=None):
        super().__init__(parent)
        self.path = Path(path)
        self.list_view = list_view
        self.viewer = viewer
        self.proxy = list_view.model() if list_view is not None else getattr(
            viewer, 'proxy_image_list_model', None)
        self.source = (self.proxy.sourceModel() if self.proxy is not None
                       and hasattr(self.proxy, 'sourceModel') else self.proxy)
        self.directory = getattr(self.source, '_directory_path', None)
        self.index = QPersistentModelIndex()
        self._cached_rank = None
        self._cached_generation = None
        self._pending = None
        self._closed = False
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._progress)
        self._remember_index(index)
        if self.proxy is not None:
            for name in ('modelReset', 'layoutChanged', 'rowsInserted', 'rowsRemoved',
                         'filter_changed', 'pages_updated'):
                signal = getattr(self.proxy, name, None)
                if signal is not None:
                    signal.connect(self._model_changed)
            self.proxy.destroyed.connect(self._model_changed)

    def _valid_owner(self):
        if self._closed:
            return False
        try:
            if self.proxy is None or not isValid(self.proxy) or self.source is None or not isValid(self.source):
                return False
            if hasattr(self.proxy, 'sourceModel') and self.proxy.sourceModel() is not self.source:
                return False
            if getattr(self.source, '_directory_path', None) != self.directory:
                return False
            if self.list_view is not None:
                return isValid(self.list_view) and self.list_view.model() is self.proxy
            return (self.viewer is not None and isValid(self.viewer)
                    and self.viewer.proxy_image_list_model is self.proxy)
        except RuntimeError:
            return False

    @staticmethod
    def _image(index):
        try:
            return index.data(Qt.ItemDataRole.UserRole) if index.isValid() else None
        except RuntimeError:
            return None

    def _remember_index(self, index):
        try:
            fresh = QModelIndex(index) if index is not None else QModelIndex()
            image = self._image(fresh)
            if (fresh.isValid() and fresh.model() is self.proxy and image is not None
                    and Path(image.path) == self.path):
                self.index = QPersistentModelIndex(fresh)
                return fresh
        except (RuntimeError, TypeError, AttributeError):
            pass
        return QModelIndex()

    def _current_index(self):
        if not self._valid_owner():
            return QModelIndex()
        index = self._remember_index(self.index)
        if index.isValid():
            return index
        # A page refresh can invalidate a persistent row. Rebind by exact path,
        # using resident data only; do not perform a database lookup on the UI thread.
        find_row = getattr(self.source, 'get_loaded_row_for_path', None)
        if not callable(find_row):
            return QModelIndex()
        row = find_row(self.path)
        if row < 0:
            return QModelIndex()
        source_index = self.source.index(row, 0)
        index = (self.proxy.mapFromSource(source_index)
                 if hasattr(self.proxy, 'mapFromSource') else source_index)
        return self._remember_index(index)

    def _global_rank(self, index):
        source_index = (self.proxy.mapToSource(index)
                        if hasattr(self.proxy, 'mapToSource') else index)
        if not source_index.isValid():
            return -1
        return int(self.source.get_global_index_for_row(source_index.row()))

    def _position(self):
        if not self._valid_owner() or getattr(self.source, '_view_prepare_owner', None) is not None:
            return None
        index = self._current_index()
        if not index.isValid():
            if (getattr(self.source, '_paginated_mode', False)
                    and self._cached_generation == getattr(self.source, '_page_load_generation', None)):
                count = int(getattr(self.source, '_total_count', 0) or 0)
                if isinstance(self._cached_rank, int) and 0 <= self._cached_rank < count:
                    return self._cached_rank, count
            return None
        if getattr(self.source, '_paginated_mode', False):
            rank = self._global_rank(index)
            count = int(getattr(self.source, '_total_count', 0) or 0)
            if 0 <= rank < count:
                self._cached_rank = rank
                self._cached_generation = getattr(self.source, '_page_load_generation', None)
        else:
            rank, count = index.row(), self.proxy.rowCount()
        return (rank, count) if 0 <= rank < count else None

    def availability(self):
        if self._pending is not None:
            return False, False
        position = self._position()
        if position is None:
            return False, False
        rank, count = position
        return rank > 0, rank + 1 < count

    def move(self, delta):
        if self._pending is not None or delta not in (-1, 1):
            return
        position = self._position()
        if position is None:
            return
        rank, count = position
        target = rank + delta
        if not 0 <= target < count:
            return
        if not getattr(self.source, '_paginated_mode', False):
            self._activate(self.proxy.index(target, 0))
            return

        self._pending = {
            'anchor_path': self.path, 'anchor_rank': rank, 'target': target,
            'generation': getattr(self.source, '_page_load_generation', None),
            'deadline': time.monotonic() + 30.0, 'started': False,
            'committed': False, 'target_path': None,
        }
        self.changed.emit()
        self._timer.start()
        self._progress()

    def _index_for_rank(self, rank):
        row = self.source.get_loaded_row_for_global_index(rank)
        if row < 0:
            return QModelIndex()
        source_index = self.source.index(row, 0)
        index = (self.proxy.mapFromSource(source_index)
                 if hasattr(self.proxy, 'mapFromSource') else source_index)
        if not index.isValid() or self._global_rank(index) != rank:
            return QModelIndex()
        return index

    def _commit_list_selection(self, index):
        owner = getattr(self.list_view, '_secondary_browser_owner', None)
        if owner is None:
            owner = self.list_view._main_window_host()
        commit = getattr(owner, 'commit_thumbnail_click_selection', None)
        if callable(commit):
            commit(index)

    def _list_viewer_has_path(self, path):
        host = self.list_view._main_window_host()
        viewer = getattr(host, 'image_viewer', None)
        media = getattr(viewer, 'current_media', None)
        return (getattr(viewer, 'proxy_image_list_model', None) is self.proxy
                and media is not None and Path(media.path) == path)

    def _activate(self, index, *, selection_already_set=False):
        if not self._valid_owner():
            self._fail('The original media list is no longer available.')
            return
        image = self._image(index)
        if image is None or not getattr(image, 'path', None):
            self._fail('Could not find that file in the media list.')
            return
        path = Path(image.path)
        if self.list_view is not None:
            if not selection_already_set:
                self.list_view.set_current_index_preserving_virtual_selection(index)
            # Selection callbacks can replace model rows; never commit a stale index.
            current = self.list_view.currentIndex()
            current_image = self._image(current)
            if current_image is None or Path(current_image.path) != path:
                self._fail('The media list changed while navigating.')
                return
            if not self._list_viewer_has_path(path):
                self._commit_list_selection(current)
            if not self._list_viewer_has_path(path):
                self._fail('Could not open that file in the viewer.')
                return
            index = current
        else:
            self.viewer.load_image(index)
            displayed = getattr(self.viewer, 'current_media', None)
            if displayed is None or Path(displayed.path) != path:
                self._fail('Could not open that file in the viewer.')
                return
        self._finish(index, path)

    def _finish(self, index, path):
        self._pending = None
        self._timer.stop()
        self.path = path
        self.index = QPersistentModelIndex(index)
        self._cached_rank = None
        self._cached_generation = None
        self.navigated.emit(path)
        self.changed.emit()

    def _fail(self, message):
        self._pending = None
        self._timer.stop()
        self.failed.emit(message)
        self.changed.emit()

    def _model_changed(self, *_args):
        if self._closed:
            return
        if self._pending is None:
            self.changed.emit()
        else:
            QTimer.singleShot(0, self, self._progress)

    def _progress(self):
        pending = self._pending
        if pending is None:
            return
        if (not self._valid_owner()
                or getattr(self.source, '_page_load_generation', None) != pending['generation']):
            self._fail('The media list changed while navigating.')
            return
        if time.monotonic() >= pending['deadline']:
            self._fail('Timed out while loading the next file.')
            return

        anchor = self._index_for_rank(pending['anchor_rank'])
        anchor_image = self._image(anchor)
        if anchor_image is None:
            page_size = max(1, int(getattr(self.source, 'PAGE_SIZE', 1000) or 1000))
            self.source._request_page_load(pending['anchor_rank'] // page_size)
            return
        if anchor_image is not None and Path(anchor_image.path) != pending['anchor_path']:
            self._fail('The media list changed while navigating.')
            return
        target = self._index_for_rank(pending['target'])
        if not target.isValid():
            # Load cold pages asynchronously before asking the browser to
            # relocate. Its virtual-list path can otherwise load synchronously.
            page_size = max(1, int(getattr(self.source, 'PAGE_SIZE', 1000) or 1000))
            self.source._request_page_load(pending['target'] // page_size)
            return
        if self.list_view is None:
            self._activate(target)
            return

        target_image = self._image(target)
        if target_image is None:
            return
        target_path = Path(target_image.path)
        if not pending['started']:
            selected = self.list_view.select_resident_neighbor(target, pending['target'])
            if selected is None:
                return
            if selected:
                current = self.list_view.currentIndex()
                image = self._image(current)
                if (image is None or Path(image.path) != target_path
                        or self._global_rank(current) != pending['target']):
                    self._fail('The media list changed while navigating.')
                    return
                self._activate(current, selection_already_set=True)
                return
            pending['started'] = True
            pending['target_path'] = target_path
            # Reuse the browser's rank-anchored navigation so selection
            # survives masonry and virtual-list page refreshes.
            self.list_view._pending_explicit_jump_kind = 'index_input'
            if not self.list_view.go_to_global_index(pending['target']):
                self._fail('Could not navigate to the next file.')
            return
        if target_path != pending['target_path']:
            self._fail('The media list changed while navigating.')
            return
        current = self.list_view.currentIndex()
        if (not current.isValid() or self._global_rank(current) != pending['target']
                or self._image(current) is None):
            return
        if getattr(self.list_view, '_one_shot_jump_target_global', None) is not None:
            return
        image = self._image(current)
        if Path(image.path) != pending['target_path']:
            self._fail('The media list changed while navigating.')
            return
        if not pending['committed']:
            pending['committed'] = True
            if not self._list_viewer_has_path(target_path):
                self._commit_list_selection(current)
        current = self.list_view.currentIndex()
        image = self._image(current)
        if (image is None or Path(image.path) != target_path
                or self._global_rank(current) != pending['target']):
            return
        if self._list_viewer_has_path(target_path):
            self._finish(current, target_path)

    def close(self):
        self._closed = True
        self._pending = None
        self._timer.stop()
