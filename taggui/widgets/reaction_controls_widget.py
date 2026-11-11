"""Reusable reaction controls cluster for toolbar and overlay hosting."""

from PySide6.QtCore import QMimeData, QPoint, QSize, Qt, Signal
from PySide6.QtGui import QDrag, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QToolButton, QWidget

from utils.review_marks import get_review_sticker_spec_for_reaction
from widgets.rating_controls import ReactionToggleButton, StarRatingWidget
from widgets.reaction_sticker_art import draw_reaction_sticker_art
from widgets.review_controls_widget import BADGE_MIME


class DraggableReactionToggleButton(ReactionToggleButton):
    """Keep reaction toggling while also allowing drag-to-place stickers."""

    def __init__(self, kind: str, parent=None):
        super().__init__(kind, parent)
        self._drag_start_pos = None
        self.setToolTip(f'{self.toolTip()}\nDrag onto an image to place a sticker')

    def mousePressEvent(self, event):
        self._drag_start_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (
            self._drag_start_pos is not None
            and self.isDown()
            and not self._filter_click_active
            and event.buttons() & Qt.MouseButton.LeftButton
            and (event.position().toPoint() - self._drag_start_pos).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            spec = get_review_sticker_spec_for_reaction(self._kind)
            if spec is None:
                return super().mouseMoveEvent(event)
            drag = QDrag(self)
            mime = QMimeData()
            mime.setData(BADGE_MIME, spec.badge_id.encode('utf-8'))
            drag.setMimeData(mime)
            pixmap = QPixmap(48, 48)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            draw_reaction_sticker_art(painter, pixmap.rect(), self._kind)
            painter.end()
            drag.setPixmap(pixmap)
            drag.setHotSpot(QPoint(24, 24))
            self.setDown(False)
            self._drag_start_pos = None
            drag.exec(Qt.DropAction.CopyAction)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_start_pos = None
        super().mouseReleaseEvent(event)


class ReactionControlsWidget(QFrame):
    """Compact star/love/bomb cluster with optional viewer attach toggle."""

    hover_changed = Signal(bool)

    def __init__(
        self,
        toolbar_manager,
        *,
        overlay_mode: bool = False,
        compact_mode: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.toolbar_manager = toolbar_manager
        self._overlay_mode = bool(overlay_mode)
        self._compact_mode = bool(compact_mode)
        self.setObjectName("reactionControlsWidget")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            2 if self._compact_mode else 8,
            0 if self._compact_mode else 6,
            2 if self._compact_mode else 8,
            0 if self._compact_mode else 6,
        )
        layout.setSpacing(3 if self._compact_mode else 6)

        self._host_toggle_button = self._make_action_button(
            toolbar_manager.reaction_controls_host_toggle_action,
            role="host_toggle",
        )
        layout.addWidget(self._host_toggle_button)

        spacer = QWidget(self)
        spacer.setFixedWidth(2 if self._compact_mode else 4)
        spacer.setObjectName("reactionControlsSpacer")
        layout.addWidget(spacer)

        self.rating_widget = StarRatingWidget(self)
        if self._compact_mode:
            self.rating_widget.setFixedHeight(26)
        layout.addWidget(self.rating_widget)

        self.love_button = DraggableReactionToggleButton('love', self)
        if self._compact_mode:
            self.love_button.setFixedSize(28, 28)
        layout.addWidget(self.love_button)

        self.bomb_button = DraggableReactionToggleButton('bomb', self)
        if self._compact_mode:
            self.bomb_button.setFixedSize(28, 28)
        layout.addWidget(self.bomb_button)

        self.set_overlay_mode(self._overlay_mode)

    def _make_action_button(self, action, *, role: str = "host_toggle"):
        button = QToolButton(self)
        button.setDefaultAction(action)
        button.setAutoRaise(False)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setProperty("controlRole", role)
        button.setFixedSize(14, 20 if self._compact_mode else 28)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        return button

    def sizeHint(self) -> QSize:
        if self._compact_mode:
            return super().sizeHint().expandedTo(QSize(232, 24))
        return super().sizeHint().expandedTo(QSize(238, 42))

    def minimumSizeHint(self) -> QSize:
        if self._compact_mode:
            return QSize(220, 24)
        return QSize(216, 40)

    def set_overlay_mode(self, overlay_mode: bool):
        self._overlay_mode = bool(overlay_mode)
        if self._overlay_mode:
            self.setStyleSheet(
                """
                #reactionControlsWidget {
                    background: rgba(18, 22, 28, 150);
                    border: 1px solid rgba(210, 220, 235, 80);
                    border-radius: 8px;
                }
                #reactionControlsWidget QToolButton[controlRole="host_toggle"] {
                    background: transparent;
                    color: rgba(226, 232, 240, 180);
                    border: none;
                    border-radius: 7px;
                    font-size: 12px;
                    font-weight: 700;
                    padding: 0px;
                }
                #reactionControlsWidget QToolButton[controlRole="host_toggle"]:hover {
                    background: rgba(255, 255, 255, 26);
                    color: rgba(248, 250, 252, 230);
                }
                #reactionControlsWidget QToolButton[controlRole="host_toggle"]:pressed {
                    background: rgba(255, 255, 255, 42);
                }
                #reactionControlsWidget QToolButton[controlRole="host_toggle"]:checked {
                    color: rgba(164, 243, 197, 220);
                }
                """
            )
        else:
            self.setStyleSheet(
                """
                #reactionControlsWidget {
                    background: transparent;
                    border: none;
                }
                #reactionControlsWidget QToolButton[controlRole="host_toggle"] {
                    background: transparent;
                    color: #d7dee8;
                    border: none;
                    border-radius: 7px;
                    font-size: 12px;
                    font-weight: 700;
                    padding: 0px;
                }
                #reactionControlsWidget QToolButton[controlRole="host_toggle"]:hover {
                    background: rgba(255, 255, 255, 0.08);
                    color: #f8fafc;
                }
                #reactionControlsWidget QToolButton[controlRole="host_toggle"]:pressed {
                    background: rgba(255, 255, 255, 0.14);
                }
                #reactionControlsWidget QToolButton[controlRole="host_toggle"]:checked {
                    color: #9ae6b4;
                }
                """
            )

    def enterEvent(self, event):
        self.hover_changed.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hover_changed.emit(False)
        super().leaveEvent(event)
