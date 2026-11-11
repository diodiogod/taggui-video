"""Main still-image viewer interactions for positioned review badges."""

from dataclasses import dataclass, replace
import time
from uuid import uuid4

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QGraphicsItem, QGraphicsPixmapItem, QMenu, QToolTip

from utils.review_marks import (
    ReviewFlag,
    ReviewSticker,
    get_review_badge_corner_radius,
    get_review_badge_font_size,
    get_review_badge_spec_for_flag,
    get_review_badge_spec_for_id,
    get_review_badge_spec_for_rank,
    get_review_badge_text_color,
    get_review_sticker_spec_for_id,
    get_review_sticker_spec_for_reaction,
    get_review_sticker_specs,
    normalize_review_state,
)
from utils.settings import (
    DEFAULT_SETTINGS,
    get_thumbnail_review_badge_style_spec,
    settings,
)
from widgets.review_badge_paint import draw_review_badge
from widgets.reaction_sticker_art import draw_reaction_sticker_art, reaction_sticker_frame_size
from widgets.review_controls_widget import BADGE_MIME


@dataclass
class _StickerPlacement:
    model: object
    media_path: str
    badge_id: str
    progress: float = 0.0
    last_tick: float | None = None
    active: bool = False


class StickerItem(QGraphicsPixmapItem):
    def __init__(self, sticker, spec, *, interactive=True):
        super().__init__()
        self.sticker = sticker
        self.base_size = max(
            12,
            min(
                96,
                settings.value(
                    'review_sticker_size',
                    DEFAULT_SETTINGS['review_sticker_size'],
                    type=int,
                ),
            ),
        )
        self.spec = spec
        self.display_scale = 1.25 if spec.kind == 'reaction' else 1.0
        self.logical_size = None
        self.placement_progress = 1.0
        self._hover_help_cursor = None
        self.set_size(self.base_size + sticker.size_offset)
        self._sticker_tooltip = (
            'Right-click to change or remove. Right-drag or Alt+left-drag '
            'horizontally to resize.'
            if interactive else f'{spec.label} {spec.title}'.strip()
        )
        self.setToolTip(self._sticker_tooltip)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setZValue(100)

    def set_size(self, size):
        logical_size = max(12, min(96, int(round(size))))
        if self.logical_size == logical_size:
            return
        self.logical_size = logical_size
        self._render()

    def set_placement_progress(self, progress):
        progress = max(0.0, min(1.0, float(progress)))
        if self.placement_progress != progress:
            self.placement_progress = progress
            if progress < 1.0:
                # A stationary placement cursor must not open a help label
                # during the transition or as it settles. Mouse movement
                # restores ordinary hover help after the animation.
                self.setToolTip('')
                self._hover_help_cursor = QCursor.pos()
            self._render()

    def restore_hover_help(self):
        if (self.placement_progress >= 1.0
                and (self._hover_help_cursor is None or self._hover_help_cursor != QCursor.pos())):
            self.setToolTip(self._sticker_tooltip)
            self._hover_help_cursor = None

    def _render(self):
        render_size = max(12, int(round(self.logical_size * self.display_scale)))
        if self.spec.kind == 'reaction':
            render_size = reaction_sticker_frame_size(
                render_size, self.spec.reaction_name, self.placement_progress,
            )
        pixmap = QPixmap(render_size, render_size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.spec.kind == 'reaction':
            draw_reaction_sticker_art(
                painter,
                QRectF(pixmap.rect()).adjusted(1, 1, -1, -1),
                self.spec.reaction_name,
                progress=self.placement_progress,
            )
        else:
            scale = self.logical_size / 26
            font = QFont()
            font.setBold(True)
            font.setPointSizeF(get_review_badge_font_size() * scale)
            painter.setFont(font)
            style = get_thumbnail_review_badge_style_spec(settings.value('thumbnail_review_badge_style', type=str))
            text_color = QColor(get_review_badge_text_color())
            text_color.setAlpha(245)
            draw_review_badge(painter, pixmap.rect().adjusted(1, 1, -2, -2), self.spec.label,
                              QColor(self.spec.color), style, get_review_badge_corner_radius() * scale, text_color)
        painter.end()
        self.setPixmap(pixmap)
        self.setOffset(-render_size / 2, -render_size / 2)


class StickerMenu(QMenu):
    def keyReleaseEvent(self, event):
        # Releasing the opening modifier should leave the picker available for a click.
        if event.key() in (Qt.Key.Key_Alt, Qt.Key.Key_AltGr):
            event.accept()
            return
        super().keyReleaseEvent(event)


class ReviewStickerControls(QObject):
    edited = Signal(object, object, object, int, int, int, str, object, object)

    def __init__(self, viewer, *, interactive=True):
        super().__init__(viewer)
        self.viewer = viewer
        self.view = viewer.view
        self.interactive = bool(interactive)
        self.dragging = None
        self.left_resize = None
        self.menu_press = None
        self.resize_item = None
        self.resizing = False
        self.consume_mouse_context = False
        self.raw_press = None
        self.raw_menu_timer = QTimer(self)
        self.raw_menu_timer.setSingleShot(True)
        self.raw_menu_timer.setInterval(50)
        self.raw_menu_timer.timeout.connect(self._finish_raw_click)
        self._placements = {}
        self._placement_timer = QTimer(self)
        self._placement_timer.setInterval(16)
        self._placement_timer.timeout.connect(self._advance_placements)
        if self.interactive:
            self.view.setAcceptDrops(True)
            self.view.viewport().setAcceptDrops(True)
            self.view.installEventFilter(self)
            self.view.viewport().installEventFilter(self)
        self.items = []

    def refresh(self, image):
        allowed = {sticker.id: sticker.badge_id for sticker in image.review_stickers} if image else {}
        model = self.viewer.proxy_image_list_model.sourceModel()
        for sticker_id, placement in list(self._placements.items()):
            if (image is None or str(image.path) != placement.media_path
                    or placement.model is not model
                    or allowed.get(sticker_id) != placement.badge_id):
                self._placements.pop(sticker_id)
            else:
                # Saving metadata can rebuild the scene. Keep its animation phase
                # and exclude the time spent waiting for the new scene pixels.
                placement.last_tick = None
        if not self._placements:
            self._placement_timer.stop()
        for item in self.items:
            if self.viewer._is_live_scene_item(item):
                self.viewer.scene.removeItem(item)
        self.resize_item = None
        self.menu_press = None
        self.left_resize = None
        self.items.clear()
        self.raw_press = None
        self.dragging = None
        rect = self.bounds()
        if rect is None or image is None:
            return
        for sticker in image.review_stickers:
            spec = get_review_sticker_spec_for_id(sticker.badge_id)
            if spec:
                item = StickerItem(sticker, spec, interactive=self.interactive)
                item.setPos(rect.topLeft() + QPointF(rect.width() * sticker.x, rect.height() * sticker.y))
                placement = self._placements.get(sticker.id)
                if placement:
                    item.set_placement_progress(placement.progress)
                self.viewer.scene.addItem(item)
                self.items.append(item)

    def _advance_placements(self):
        now = time.monotonic()
        current = self.viewer.current_media
        model = self.viewer.proxy_image_list_model.sourceModel()
        for sticker_id, placement in list(self._placements.items()):
            item = next((item for item in self.items if item.sticker.id == sticker_id), None)
            if (placement.model is not model or not self.viewer.isVisible()
                    or (current is not None and str(current.path) != placement.media_path)):
                self._placements.pop(sticker_id)
                if item is not None and self.viewer._is_live_scene_item(item):
                    item.set_placement_progress(1.0)
                continue
            if (not placement.active or current is None or item is None
                    or not self.viewer._is_live_scene_item(item)):
                placement.last_tick = None
                continue
            if placement.last_tick is not None:
                duration = 0.82 if item.spec.reaction_name == 'love' else 1.16
                placement.progress = min(1.0, placement.progress + (now - placement.last_tick) / duration)
            placement.last_tick = now
            item.set_placement_progress(placement.progress)
            if placement.progress >= 1.0:
                self._placements.pop(sticker_id)
        if not self._placements:
            self._placement_timer.stop()

    def _finish_placement(self, item):
        if item is not None:
            self._placements.pop(item.sticker.id, None)
            item.set_placement_progress(1.0)
        if not self._placements:
            self._placement_timer.stop()

    def bounds(self):
        item = self.viewer.current_image_item
        if (item is None or self.viewer.is_compare_mode_active()
                or not self.viewer._is_live_scene_item(item)):
            return None
        rect = item.sceneBoundingRect()
        return None if rect.isEmpty() else rect

    def target(self, pos):
        rect = self.bounds()
        point = self.view.mapToScene(pos)
        if rect is None or not rect.contains(point):
            return None
        _, model, image = self.viewer.get_live_image_context()
        if image is None or image is not self.viewer.current_media:
            return None
        x = (point.x() - rect.x()) / rect.width()
        y = (point.y() - rect.y()) / rect.height()
        return model, image, x, y

    @staticmethod
    def _reaction_changes(image, stickers):
        changes = []
        for badge_id, attribute in (
            ('reaction_love', 'love'),
            ('reaction_bomb', 'bomb'),
        ):
            was_present = any(
                sticker.badge_id == badge_id for sticker in image.review_stickers
            )
            is_present = any(sticker.badge_id == badge_id for sticker in stickers)
            changes.append(is_present if was_present != is_present else None)
        return tuple(changes)

    def place(self, target, spec, previous=None):
        model, image, x, y = target
        flags, rank = image.review_flags, image.review_rank
        owned = image.sticker_owned_flags & flags
        stickers = image.review_stickers
        if previous is not None:
            if previous not in stickers or (spec and spec.badge_id == previous.badge_id):
                return
            old_spec = get_review_badge_spec_for_id(previous.badge_id)
            if old_spec and not any(s != previous and s.badge_id == previous.badge_id for s in stickers):
                flags &= ~(owned & int(old_spec.flag))
                owned &= ~int(old_spec.flag)
            if spec is None:
                remaining = tuple(s for s in stickers if s != previous)
                self.edited.emit(
                    model, image, remaining, owned, rank, flags,
                    'Remove review sticker', *self._reaction_changes(image, remaining),
                )
                return
            replacement = replace(previous, badge_id=spec.badge_id)
            stickers = tuple(s for s in stickers if s != previous) + (replacement,)
            placed_sticker = replacement
            action = 'Replace review sticker'
        else:
            placed_sticker = ReviewSticker(uuid4().hex, spec.badge_id, x, y)
            stickers = (*stickers, placed_sticker)
            action = 'Place review sticker'
        if spec.kind == 'rank':
            rank = spec.rank
            flags &= ~int(ReviewFlag.REJECT)
        elif spec.kind == 'flag':
            flag = int(spec.flag)
            owned |= flag & ~flags
            flags |= flag
        rank, flags = normalize_review_state(rank, flags)
        love, bomb = self._reaction_changes(image, stickers)
        if spec.kind == 'reaction':
            if spec.reaction_name == 'love':
                love = True
            elif spec.reaction_name == 'bomb':
                bomb = True
            QToolTip.hideText()
            self._placements[placed_sticker.id] = _StickerPlacement(
                model, str(image.path), spec.badge_id,
            )
        self.edited.emit(
            model, image, stickers, owned & flags, rank, flags, action, love, bomb,
        )
        placement = self._placements.get(placed_sticker.id)
        if placement is not None:
            if placed_sticker in image.review_stickers:
                placement.active = True
                self._placement_timer.start()
                self._advance_placements()
            else:
                self._placements.pop(placed_sticker.id)

    def shortcut(self, kind, value):
        viewport = self.view.viewport()
        pos = QCursor.pos()
        if QApplication.widgetAt(pos) is not viewport or QApplication.activePopupWidget():
            return False
        target = self.target(viewport.mapFromGlobal(pos))
        if not target:
            return False
        if kind == 'reaction':
            spec = get_review_sticker_spec_for_reaction(value)
        else:
            spec = (get_review_badge_spec_for_rank(value) if kind == 'rank'
                    else get_review_badge_spec_for_flag(value))
        if spec:
            self.place(target, spec)
        return bool(spec)

    def item_at(self, pos):
        return next((item for item in self.view.items(pos) if isinstance(item, StickerItem)), None)

    def menu(self, pos):
        target = self.target(pos)
        if not target:
            return
        model, image, _, _ = target
        item = self.item_at(pos)
        sticker = item.sticker if item else None
        menu = StickerMenu(self.view)
        menu.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
        actions = {menu.addAction(f'{spec.label}  {spec.title}'): spec for spec in get_review_sticker_specs()
                   if sticker is None or spec.badge_id != sticker.badge_id}
        clear_all = None
        if image.review_stickers:
            menu.addSeparator()
            clear_all = menu.addAction('Clear all stickers')
        remove = None
        if sticker:
            menu.addSeparator()
            remove = menu.addAction('Remove this sticker')
        selected = menu.exec(self.view.viewport().mapToGlobal(pos))
        menu.deleteLater()
        current = self.target(pos)
        if not selected or not current or current[0] is not model or current[1] is not image:
            return
        if selected in actions:
            self.place(target, actions[selected], sticker)
        elif selected == remove:
            self.place(target, None, sticker)
        elif selected == clear_all:
            flags = image.review_flags & ~image.sticker_owned_flags
            self.edited.emit(
                model,
                image,
                (),
                0,
                image.review_rank,
                flags,
                'Clear review stickers',
                *self._reaction_changes(image, ()),
            )

    def begin_right_press(self, pos, owner):
        self.menu_press = (pos, owner)
        self.resize_item = self.item_at(pos)
        self._finish_placement(self.resize_item)
        self.resizing = False
        if self.resize_item:
            self.start_size = self.resize_item.logical_size
        self.consume_mouse_context = True

    def preview_left_resize(self, pos):
        if self.left_resize is None:
            return
        item, owner, start, original_size, resizing = self.left_resize
        if not self.viewer._is_live_scene_item(item):
            self.left_resize = None
            return
        dx = pos.x() - start.x()
        if resizing or abs(dx) >= QApplication.startDragDistance():
            item.set_size(max(12, min(96, original_size + dx)))
            self.left_resize = item, owner, start, original_size, True

    def finish_left_resize(self, pos):
        self.preview_left_resize(pos)
        state, self.left_resize = self.left_resize, None
        if state is None:
            return
        item, owner, _start, original_size, resizing = state
        if not resizing:
            return
        size = item.logical_size
        if size == original_size or item.sticker not in owner.review_stickers:
            return
        _, model, _image = self.viewer.get_live_image_context()
        self._commit_resize(item, owner, original_size, model)

    def _commit_resize(self, item, owner, original_size, model):
        if model is None:
            item.set_size(original_size)
            return
        _, live_model, live_image = self.viewer.get_live_image_context()
        if live_model is not model or live_image is not owner:
            item.set_size(original_size)
            return
        if item.logical_size == original_size or item.sticker not in owner.review_stickers:
            return
        stickers = tuple(
            replace(sticker, size_offset=item.logical_size - item.base_size)
            if sticker == item.sticker else sticker
            for sticker in owner.review_stickers
        )
        self.edited.emit(
            model,
            owner,
            stickers,
            owner.sticker_owned_flags,
            owner.review_rank,
            owner.review_flags,
            'Resize review sticker',
            None,
            None,
        )

    def preview_right_drag(self, pos):
        if self.resize_item is None or self.menu_press is None:
            return
        dx = pos.x() - self.menu_press[0].x()
        if self.resizing or abs(dx) >= QApplication.startDragDistance():
            self.resizing = True
            self.resize_item.set_size(max(12, min(96, self.start_size + dx)))

    def finish_right_press(self, pos):
        self.preview_right_drag(pos)
        start, owner = self.menu_press
        item, resizing = self.resize_item, self.resizing
        self.menu_press = self.resize_item = None
        self.resizing = False
        target = self.target(start)
        if not target or target[1] is not owner:
            if item:
                item.set_size(self.start_size)
            return
        if resizing:
            self._commit_resize(item, owner, self.start_size, target[0])
        elif (pos - start).manhattanLength() < QApplication.startDragDistance():
            self.menu(start)

    def _finish_raw_click(self):
        press, self.raw_press = self.raw_press, None
        if not press or QApplication.activePopupWidget():
            return
        pos, owner = press
        viewport = self.view.viewport()
        cursor = QCursor.pos()
        if self.menu_press == press:
            self.finish_right_press(viewport.mapFromGlobal(cursor))

    def wants_menu(self, pos, event):
        modifiers = event.modifiers() | QApplication.queryKeyboardModifiers()
        return (bool(modifiers & (Qt.AltModifier | Qt.GroupSwitchModifier))
                or self.item_at(pos) is not None)

    def eventFilter(self, obj, event):
        kind = event.type()
        if (kind == QEvent.Type.ContextMenu and self.consume_mouse_context
                and event.reason() == event.Reason.Mouse):
            event.accept()
            return True
        if kind == QEvent.Type.ContextMenu:
            point = self.view.viewport().mapFromGlobal(event.globalPos())
            if self.wants_menu(point, event) and self.target(point):
                self.raw_press = None
                event.accept()
                self.menu(point)
                return True
        if obj is not self.view.viewport():
            return False
        if kind == QEvent.Type.MouseMove:
            for item in self.items:
                if self.viewer._is_live_scene_item(item):
                    item.restore_hover_help()
        if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.RightButton:
            if self.raw_press and self.resizing:
                event.accept()
                return True
            self.raw_press = None
            self.consume_mouse_context = False
            self.menu_press = None
            pos = event.position().toPoint()
            if self.wants_menu(pos, event):
                target = self.target(pos)
                if target:
                    self.begin_right_press(pos, target[1])
                    event.accept()
                    return True
        if (kind == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.RightButton
                and self.menu_press):
            self.raw_press = None
            self.finish_right_press(event.position().toPoint())
            event.accept()
            return True
        if kind == QEvent.Type.MouseMove and self.menu_press and event.buttons() & Qt.RightButton:
            self.preview_right_drag(event.position().toPoint())
            return True
        if kind in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop):
            mime = event.mimeData()
            if not mime.hasFormat(BADGE_MIME):
                return False
            spec = get_review_sticker_spec_for_id(bytes(mime.data(BADGE_MIME)).decode('utf-8', 'replace'))
            target = self.target(event.position().toPoint())
            if spec and (target or kind == QEvent.Type.DragEnter):
                event.acceptProposedAction()
                if kind == QEvent.Type.Drop:
                    self.place(target, spec)
            else:
                event.ignore()
            return True
        if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            item = self.item_at(pos)
            target = self.target(pos) if item else None
            if target:
                self._finish_placement(item)
                if event.modifiers() & (Qt.KeyboardModifier.AltModifier
                                        | Qt.KeyboardModifier.GroupSwitchModifier):
                    self.left_resize = (
                        item,
                        target[1],
                        pos,
                        item.logical_size,
                        False,
                    )
                    return True
                self.dragging = item, target[1], pos, item.pos()
                return True
        if self.left_resize and kind == QEvent.Type.MouseMove:
            self.preview_left_resize(event.position().toPoint())
            return True
        if (self.left_resize and kind == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.LeftButton):
            self.finish_left_resize(event.position().toPoint())
            return True
        if self.dragging and kind in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonRelease):
            item, owner, start, original = self.dragging
            pos = event.position().toPoint()
            if not self.viewer._is_live_scene_item(item):
                self.dragging = None
                return False
            delta = self.view.mapToScene(pos) - self.view.mapToScene(start)
            proposed = original + delta
            target = self.target(self.view.mapFromScene(proposed))
            if kind == QEvent.Type.MouseMove:
                if target and target[1] is owner:
                    item.setPos(proposed)
                return True
            self.dragging = None
            item.setPos(original)
            if target and target[1] is owner and (pos - start).manhattanLength() >= QApplication.startDragDistance():
                model, image, x, y = target
                stickers = tuple(replace(s, x=x, y=y) if s.id == item.sticker.id else s
                                 for s in image.review_stickers)
                self.edited.emit(model, image, stickers, image.sticker_owned_flags,
                                 image.review_rank, image.review_flags, 'Move review sticker',
                                 None, None)
            return True
        return False
