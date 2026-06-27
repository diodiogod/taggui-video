from PySide6.QtCore import Qt, Slot, QUrl, QThread, Signal, QRectF, QPointF
from PySide6.QtGui import QDesktopServices, QColor, QPainter, QPen, QLinearGradient, QPainterPath, QFont
from PySide6.QtWidgets import (QDialog, QFileDialog, QGridLayout, QLabel,
                               QLineEdit, QPushButton, QVBoxLayout, QComboBox,
                               QScrollArea, QWidget, QTabWidget, QMessageBox, QHBoxLayout, QColorDialog,
                               QApplication, QGroupBox, QProgressDialog, QGraphicsItem,
                               QGraphicsRectItem, QGraphicsScene, QGraphicsSimpleTextItem,
                               QGraphicsTextItem,
                               QGraphicsView)

from pathlib import Path
import sys
import shutil
import subprocess
import threading
from utils.settings import (
    DEFAULT_SETTINGS,
    THUMBNAIL_BADGE_STYLE_OPTIONS,
    THUMBNAIL_STAR_BADGE_STYLE_OPTIONS,
    parse_image_list_formats,
    get_thumbnail_reaction_badge_style_spec,
    get_thumbnail_review_badge_style_spec,
    get_thumbnail_star_badge_style_spec,
    normalize_thumbnail_badge_side,
    normalize_thumbnail_reaction_badge_style,
    normalize_thumbnail_review_badge_style,
    normalize_thumbnail_star_badge_style,
    settings,
)
from utils.video.playback_backend import (
    PLAYBACK_BACKEND_CHOICES,
    PLAYBACK_BACKEND_QT_HYBRID,
    MPV_BACKEND_AVAILABLE,
    MPV_BACKEND_ERROR,
    MPV_RUNTIME_SEARCHED_DIRS,
    VLC_BACKEND_AVAILABLE,
    VLC_BACKEND_ERROR,
    VLC_RUNTIME_SEARCHED_DIRS,
    resolve_runtime_playback_backend,
    normalize_playback_backend_name,
)
from utils.settings_widgets import (SettingsBigCheckBox, SettingsLineEdit,
                                    SettingsSpinBox, SettingsComboBox,
                                    SettingsSlider)
from utils.grammar_checker import GrammarCheckMode
from utils.image_index_db import ImageIndexDB
from utils.review_marks import (
    REVIEW_BADGE_CORNER_RADIUS_SETTINGS_KEY,
    REVIEW_BADGE_FONT_SIZE_SETTINGS_KEY,
    REVIEW_BADGE_SCHEMA_SETTINGS_KEY,
    REVIEW_BADGE_TEXT_COLOR_SETTINGS_KEY,
    get_review_badge_corner_radius,
    get_review_badge_font_size,
    get_review_badge_specs,
    get_review_badge_text_color,
    reset_review_badge_schema,
    save_review_badge_schema,
)
from utils.thumbnail_cache import get_thumbnail_cache
from widgets.ideogram_label_item import IdeogramLabelItem


class ExtensionlessRepairThread(QThread):
    progress_changed = Signal(int, int)
    result_ready = Signal(dict)
    error_raised = Signal(str)

    def __init__(self, directory_path: Path, parent=None):
        super().__init__(parent)
        self.directory_path = Path(directory_path)
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_event.set()

    def run(self):
        try:
            from models.image_list_model import repair_extensionless_images_in_directory

            def progress_callback(file_count: int, extensionless_count: int) -> bool:
                self.progress_changed.emit(int(file_count), int(extensionless_count))
                return self._cancel_event.is_set()

            result = repair_extensionless_images_in_directory(
                self.directory_path,
                progress_callback=progress_callback,
            )
            self.result_ready.emit(result)
        except Exception as e:
            self.error_raised.emit(str(e))


class ThumbnailOverlayPreviewWidget(QWidget):
    """Live preview of thumbnail overlay badge settings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(252, 208)
        settings.change.connect(self._on_setting_changed)

    def sizeHint(self):
        return super().sizeHint().expandedTo(self.minimumSize())

    @Slot(str, object)
    def _on_setting_changed(self, key: str, _value):
        if key.startswith('thumbnail_') or key in {
            REVIEW_BADGE_SCHEMA_SETTINGS_KEY,
            REVIEW_BADGE_TEXT_COLOR_SETTINGS_KEY,
            REVIEW_BADGE_FONT_SIZE_SETTINGS_KEY,
            REVIEW_BADGE_CORNER_RADIUS_SETTINGS_KEY,
        }:
            self.update()

    def _star_value_text(self) -> str:
        return '4.5'

    def _review_style_key(self) -> str:
        return normalize_thumbnail_review_badge_style(
            settings.value(
                'thumbnail_review_badge_style',
                defaultValue='Review Tile',
                type=str,
            )
        )

    def _reaction_style_key(self) -> str:
        return normalize_thumbnail_reaction_badge_style(
            settings.value(
                'thumbnail_reaction_badge_style',
                defaultValue='Review Tile',
                type=str,
            )
        )

    def _star_label(self) -> str:
        style = normalize_thumbnail_star_badge_style(
            settings.value(
                'thumbnail_star_rating_badge_style',
                defaultValue='Halo Tag: 3★',
                type=str,
            )
        )
        value_text = self._star_value_text()
        spec = get_thumbnail_star_badge_style_spec(style)
        if spec.get('label_order') == 'star_right':
            return f'{value_text}★'
        return f'★{value_text}'

    @staticmethod
    def _color_with_alpha(color: QColor, alpha: int) -> QColor:
        result = QColor(color)
        result.setAlpha(max(0, min(255, int(alpha))))
        return result

    @staticmethod
    def _blend_colors(first: QColor, second: QColor, ratio: float, alpha: int | None = None) -> QColor:
        ratio = max(0.0, min(1.0, float(ratio)))
        mixed = QColor(
            int(first.red() * (1.0 - ratio) + second.red() * ratio),
            int(first.green() * (1.0 - ratio) + second.green() * ratio),
            int(first.blue() * (1.0 - ratio) + second.blue() * ratio),
            int(first.alpha() * (1.0 - ratio) + second.alpha() * ratio),
        )
        if alpha is not None:
            mixed.setAlpha(max(0, min(255, int(alpha))))
        return mixed

    def _review_badge_palette(self, base_color: QColor, spec: dict) -> tuple[QColor, QColor, QColor]:
        fill_mode = str(spec.get('fill_mode', 'base') or 'base')
        if fill_mode == 'dark':
            fill = QColor(spec.get('dark_fill', QColor(27, 30, 37, 236)))
        elif fill_mode == 'base_soft':
            fill = QColor(base_color)
            fill.setAlpha(int(spec.get('fill_alpha', 120)))
        elif fill_mode == 'warm_base':
            fill = self._blend_colors(
                QColor(base_color),
                QColor(spec.get('warm_tint', QColor(255, 162, 102, 255))),
                float(spec.get('warm_ratio', 0.16)),
                alpha=QColor(base_color).alpha(),
            )
        else:
            fill = QColor(base_color)

        if str(spec.get('outline_mode', 'fixed') or 'fixed') == 'base':
            outline = self._color_with_alpha(QColor(base_color), int(spec.get('outline_alpha', 230)))
        else:
            outline = QColor(spec.get('outline', QColor(255, 255, 255, 235)))

        if str(spec.get('text_mode', 'fixed') or 'fixed') == 'base':
            text = self._color_with_alpha(QColor(base_color), int(spec.get('text_alpha', 255)))
        else:
            text = QColor(spec.get('text', QColor(255, 255, 255, 245)))

        return fill, outline, text

    @staticmethod
    def _reaction_badge_palette(kind: str, spec: dict) -> tuple[QColor, QColor, QColor]:
        prefix = 'love' if str(kind or '').strip().lower() == 'love' else 'bomb'
        fill = QColor(spec.get(f'{prefix}_fill', QColor(255, 255, 255, 240)))
        outline = QColor(spec.get(f'{prefix}_outline', spec.get('outline', QColor(255, 255, 255, 235))))
        icon = QColor(spec.get(f'{prefix}_icon', QColor(255, 255, 255, 255)))
        return fill, outline, icon

    def _draw_overlay_chip(
        self,
        painter: QPainter,
        rect,
        *,
        fill: QColor,
        outline: QColor,
        radius: float,
        shadow: QColor,
        text: str | None = None,
        text_color: QColor | None = None,
        path=None,
        pen_color: QColor | None = None,
        variant: str = 'solid',
        glass_highlight: QColor | None = None,
    ):
        shadow_rect = rect.translated(1, 1)
        shadow_pen = QColor(0, 0, 0, min(255, shadow.alpha() + 6))
        painter.setPen(QPen(shadow_pen, 1.1))
        painter.setBrush(shadow)
        painter.drawRoundedRect(shadow_rect, radius, radius)

        painter.setPen(QPen(outline, 1.1))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, radius, radius)

        if variant == 'glass':
            highlight = rect.adjusted(1, 1, -1, -max(5, int(rect.height() * 0.5)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(glass_highlight or QColor(255, 255, 255, 68)))
            painter.drawRoundedRect(highlight, max(3.0, radius - 2.0), max(3.0, radius - 2.0))

        if path is not None:
            painter.setPen(
                QPen(
                    pen_color or text_color or QColor(255, 255, 255),
                    1.3,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin,
                )
            )
            painter.setBrush(pen_color or text_color or QColor(255, 255, 255))
            painter.drawPath(path)
            return

        if text is not None and text_color is not None:
            painter.setPen(text_color)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _reaction_icon_path(self, kind: str, rect):
        icon_rect = rect.adjusted(3, 3, -3, -3)
        left = float(icon_rect.left())
        top = float(icon_rect.top())
        right = float(icon_rect.right())
        bottom = float(icon_rect.bottom())
        width = float(icon_rect.width())
        height = float(icon_rect.height())

        if str(kind or '').strip().lower() == 'love':
            path = QPainterPath()
            path.moveTo(left + 0.5 * width, bottom - 0.12 * height)
            path.cubicTo(
                left + 0.12 * width, top + 0.62 * height,
                left + 0.04 * width, top + 0.24 * height,
                left + 0.28 * width, top + 0.16 * height,
            )
            path.cubicTo(
                left + 0.42 * width, top + 0.10 * height,
                left + 0.50 * width, top + 0.20 * height,
                left + 0.50 * width, top + 0.28 * height,
            )
            path.cubicTo(
                left + 0.50 * width, top + 0.20 * height,
                left + 0.58 * width, top + 0.10 * height,
                left + 0.72 * width, top + 0.16 * height,
            )
            path.cubicTo(
                left + 0.96 * width, top + 0.24 * height,
                left + 0.88 * width, top + 0.62 * height,
                left + 0.50 * width, bottom - 0.12 * height,
            )
            path.closeSubpath()
            return path

        path = QPainterPath()
        center_x = left + 0.5 * width
        center_y = top + 0.5 * height
        radius = min(width, height) * 0.27
        path.addEllipse(rect.__class__(int(center_x - radius), int(center_y - radius), int(radius * 2), int(radius * 2)))
        fuse_start_x = center_x + radius * 0.45
        fuse_start_y = center_y - radius * 0.85
        fuse_mid_x = right - width * 0.18
        fuse_mid_y = top + height * 0.20
        fuse_end_x = right - width * 0.10
        fuse_end_y = top + height * 0.08
        path.moveTo(fuse_start_x, fuse_start_y)
        path.cubicTo(fuse_mid_x, fuse_mid_y, fuse_mid_x, fuse_mid_y, fuse_end_x, fuse_end_y)
        spark_radius = radius * 0.16
        path.addEllipse(
            rect.__class__(
                int(center_x + radius * 0.22 - spark_radius),
                int(center_y - radius * 0.12 - spark_radius),
                max(1, int(spark_radius * 2)),
                max(1, int(spark_radius * 2)),
            )
        )
        return path

    def _draw_chip(self, painter: QPainter, rect, *, fill: QColor, outline: QColor, text: str, text_color: QColor, radius: float):
        shadow_rect = rect.translated(1, 1)
        painter.setPen(QPen(QColor(0, 0, 0, 55), 1.2))
        painter.setBrush(QColor(0, 0, 0, 60))
        painter.drawRoundedRect(shadow_rect, radius, radius)
        painter.setPen(QPen(outline, 1.2))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, radius, radius)
        painter.setPen(text_color)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_review_badge(self, painter: QPainter, rect, label: str, base_color: QColor):
        style = self._review_style_key()
        spec = get_thumbnail_review_badge_style_spec(style)
        fill, outline, text = self._review_badge_palette(base_color, spec)
        text = QColor(get_review_badge_text_color())
        text.setAlpha(245)
        self._draw_overlay_chip(
            painter,
            rect,
            fill=fill,
            outline=outline,
            radius=float(get_review_badge_corner_radius()),
            shadow=QColor(spec.get('shadow', QColor(0, 0, 0, 60))),
            text=label,
            text_color=text,
            variant=str(spec.get('variant', 'solid') or 'solid'),
            glass_highlight=QColor(spec.get('glass_highlight', QColor(255, 255, 255, 68))),
        )

    def _draw_reaction_badge(self, painter: QPainter, rect, kind: str):
        style = self._reaction_style_key()
        spec = get_thumbnail_reaction_badge_style_spec(style)
        fill, outline, icon = self._reaction_badge_palette(kind, spec)
        self._draw_overlay_chip(
            painter,
            rect,
            fill=fill,
            outline=outline,
            radius=float(spec.get('radius', 5.0)),
            shadow=QColor(spec.get('shadow', QColor(0, 0, 0, 60))),
            path=self._reaction_icon_path(kind, rect),
            pen_color=icon,
            variant=str(spec.get('variant', 'solid') or 'solid'),
            glass_highlight=QColor(spec.get('glass_highlight', QColor(255, 255, 255, 68))),
        )

    def _draw_star_badge(self, painter: QPainter, rect, label: str, spec: dict):
        variant = str(spec.get('variant', 'pill') or 'pill')
        radius = float(spec.get('radius', 5.0))
        if variant == 'glass':
            shadow_rect = rect.translated(1, 1)
            painter.setPen(QPen(QColor(0, 0, 0, 35), 1.0))
            painter.setBrush(QColor(spec.get('shadow', QColor(0, 0, 0, 38))))
            painter.drawRoundedRect(shadow_rect, radius, radius)
            painter.setPen(QPen(QColor(spec.get('outline', QColor(255, 255, 255, 165))), 1.1))
            painter.setBrush(QColor(spec.get('fill', QColor(255, 252, 243, 112))))
            painter.drawRoundedRect(rect, radius, radius)
            highlight = rect.adjusted(1, 1, -1, -max(6, int(rect.height() * 0.55)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(spec.get('glass_highlight', QColor(255, 255, 255, 68))))
            painter.drawRoundedRect(highlight, max(3.0, radius - 2.0), max(3.0, radius - 2.0))
            painter.setPen(QColor(spec.get('text', QColor(255, 247, 230, 255))))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
            return

        if variant == 'split':
            shadow_rect = rect.translated(1, 1)
            painter.setPen(QPen(QColor(0, 0, 0, 50), 1.1))
            painter.setBrush(QColor(spec.get('shadow', QColor(0, 0, 0, 54))))
            painter.drawRoundedRect(shadow_rect, radius, radius)
            painter.setPen(QPen(QColor(spec.get('outline', QColor(255, 255, 255, 220))), 1.1))
            painter.setBrush(QColor(spec.get('fill', QColor(255, 244, 217, 228))))
            painter.drawRoundedRect(rect, radius, radius)
            star_right = spec.get('label_order') == 'star_right'
            accent_width = max(16, min(rect.width() - 10, int(spec.get('accent_width', 20))))
            if star_right:
                accent_rect = rect.__class__(rect.right() - accent_width + 1, rect.top(), accent_width, rect.height())
                value_rect = rect.__class__(rect.left(), rect.top(), rect.width() - accent_width + 1, rect.height())
            else:
                accent_rect = rect.__class__(rect.left(), rect.top(), accent_width, rect.height())
                value_rect = rect.__class__(rect.left() + accent_width - 1, rect.top(), rect.width() - accent_width + 1, rect.height())
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(spec.get('accent_fill', QColor(245, 185, 54, 246))))
            painter.drawRoundedRect(accent_rect, radius, radius)
            painter.setPen(QPen(QColor(spec.get('divider', QColor(172, 115, 0, 70))), 1.0))
            divider_x = accent_rect.right() if not star_right else accent_rect.left()
            painter.drawLine(divider_x, rect.top() + 2, divider_x, rect.bottom() - 2)
            painter.setPen(QColor(spec.get('accent_text', QColor(255, 255, 255, 255))))
            painter.drawText(accent_rect, Qt.AlignmentFlag.AlignCenter, '★')
            painter.setPen(QColor(spec.get('text', QColor(92, 54, 0, 255))))
            painter.drawText(value_rect, Qt.AlignmentFlag.AlignCenter, label.replace('★', '').strip())
            return

        if variant == 'halo':
            shadow_rect = rect.translated(1, 1)
            painter.setPen(QPen(QColor(0, 0, 0, 55), 1.1))
            painter.setBrush(QColor(spec.get('shadow', QColor(0, 0, 0, 60))))
            painter.drawRoundedRect(shadow_rect, radius, radius)
            painter.setPen(QPen(QColor(spec.get('outline', QColor(255, 214, 124, 170))), 1.1))
            painter.setBrush(QColor(spec.get('fill', QColor(40, 34, 26, 176))))
            painter.drawRoundedRect(rect, radius, radius)
            halo_diameter = max(16, min(rect.height() + 2, int(spec.get('halo_diameter', 18))))
            star_right = spec.get('label_order') == 'star_right'
            halo_y = rect.center().y() - halo_diameter / 2.0
            gap = 2
            if star_right:
                halo_x = rect.right() - halo_diameter + 1
                value_rect = rect.__class__(
                    rect.left() + 4,
                    rect.top(),
                    max(10, rect.width() - halo_diameter - gap - 5),
                    rect.height(),
                )
            else:
                halo_x = rect.left()
                value_rect = rect.__class__(
                    rect.left() + halo_diameter + gap - 2,
                    rect.top(),
                    max(10, rect.width() - halo_diameter - gap - 5),
                    rect.height(),
                )
            halo_rect = rect.__class__(
                int(halo_x),
                int(rect.top() + max(0, (rect.height() - halo_diameter) // 2)),
                int(halo_diameter),
                int(halo_diameter),
            )
            painter.setPen(QPen(QColor(255, 255, 255, 220), 1.0))
            painter.setBrush(QColor(spec.get('halo_fill', QColor(255, 210, 94, 245))))
            painter.drawEllipse(halo_rect)
            painter.setPen(QColor(spec.get('halo_text', QColor(92, 42, 0, 255))))
            painter.drawText(halo_rect, Qt.AlignmentFlag.AlignCenter, '★')
            painter.setPen(QColor(spec.get('text', QColor(255, 240, 199, 255))))
            if star_right:
                text_rect = value_rect.adjusted(1, 0, -1, 0)
                text_align = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
            else:
                text_rect = value_rect.adjusted(1, 0, -1, 0)
                text_align = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
            painter.drawText(text_rect, text_align, label.replace('★', '').strip())
            return

        self._draw_chip(
            painter,
            rect,
            fill=QColor(spec.get('fill', QColor(255, 233, 166, 245))),
            outline=QColor(spec.get('outline', QColor(255, 255, 255, 235))),
            text=label,
            text_color=QColor(spec.get('text', QColor(122, 82, 0, 255))),
            radius=radius,
        )

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        outer_rect = self.rect().adjusted(6, 6, -6, -6)
        painter.fillRect(self.rect(), self.palette().window())

        rail_height = 50
        thumb_rect = outer_rect.adjusted(18, 12, -18, -(rail_height + 10))
        gradient = QLinearGradient(thumb_rect.topLeft(), thumb_rect.bottomRight())
        gradient.setColorAt(0.0, QColor(91, 123, 154))
        gradient.setColorAt(0.45, QColor(203, 161, 116))
        gradient.setColorAt(1.0, QColor(58, 69, 91))
        painter.setPen(QPen(QColor(255, 255, 255, 42), 1.0))
        painter.setBrush(gradient)
        painter.drawRoundedRect(thumb_rect, 12, 12)

        if settings.value('thumbnail_show_review_badges', True, type=bool):
            review_font = painter.font()
            review_font.setBold(True)
            review_font.setPointSizeF(float(get_review_badge_font_size()))
            painter.setFont(review_font)
            review_rect = thumb_rect.adjusted(0, 0, 0, 0)
            badge_size = 18
            x = review_rect.right() - 5 - badge_size + 1
            y = review_rect.top() + 5
            preview_badges = [
                (str(spec.label), QColor(spec.color))
                for spec in get_review_badge_specs()[:4]
            ]
            for label, color in preview_badges:
                self._draw_review_badge(
                    painter,
                    review_rect.__class__(x, y, badge_size, badge_size),
                    label,
                    color,
                )
                x -= badge_size + 4

        reaction_side = normalize_thumbnail_badge_side(
            settings.value('thumbnail_reaction_badge_position', defaultValue='Left', type=str)
        )
        star_side = normalize_thumbnail_badge_side(
            settings.value('thumbnail_star_rating_badge_position', defaultValue='Right', type=str)
        )
        show_reactions = settings.value('thumbnail_show_reaction_badges', True, type=bool)
        show_star = settings.value('thumbnail_show_star_rating_badge', True, type=bool)

        bottom_offset = 0
        if show_reactions and show_star and reaction_side == star_side:
            bottom_offset = 22

        if show_reactions:
            badge_size = 18
            gap = 4
            kinds = ['love', 'bomb']
            total_width = len(kinds) * badge_size + (len(kinds) - 1) * gap
            if reaction_side == 'left':
                x = thumb_rect.left() + 5
            else:
                x = thumb_rect.right() - 5 - total_width + 1
            y = thumb_rect.bottom() - 5 - badge_size + 1
            text_font = painter.font()
            text_font.setPointSizeF(8.5)
            text_font.setBold(True)
            painter.setFont(text_font)
            for kind in kinds:
                self._draw_reaction_badge(
                    painter,
                    thumb_rect.__class__(x, y, badge_size, badge_size),
                    kind,
                )
                x += badge_size + gap

        if show_star:
            style = normalize_thumbnail_star_badge_style(
                settings.value(
                    'thumbnail_star_rating_badge_style',
                    defaultValue='Halo Tag: 3★',
                    type=str,
                )
            )
            spec = get_thumbnail_star_badge_style_spec(style)
            label = self._star_label()
            font = painter.font()
            font.setBold(True)
            font.setPointSizeF(float(spec.get('font_size', 9.0)))
            painter.setFont(font)
            fm = painter.fontMetrics()
            value_text = self._star_value_text()
            variant = str(spec.get('variant', 'pill') or 'pill')
            if variant == 'halo':
                halo_diameter = max(16, min(20, int(spec.get('halo_diameter', 18))))
                width = int(fm.horizontalAdvance(value_text)) + halo_diameter + int(spec.get('padding_x', 18))
            elif variant == 'split':
                accent_width = max(16, int(spec.get('accent_width', 20)))
                width = int(fm.horizontalAdvance(value_text)) + accent_width + int(spec.get('padding_x', 16))
            else:
                width = int(fm.horizontalAdvance(label)) + int(spec.get('padding_x', 12))
            width = max(26, int(width))
            height = 18
            y = thumb_rect.bottom() - 5 - height + 1 - bottom_offset
            if star_side == 'left':
                x = thumb_rect.left() + 5
            else:
                x = thumb_rect.right() - 5 - width + 1
            self._draw_star_badge(
                painter,
                thumb_rect.__class__(x, y, width, height),
                label,
                spec,
            )

        rail_rect = outer_rect.adjusted(12, thumb_rect.bottom() + 10, -12, -8)
        painter.setPen(QPen(QColor(255, 255, 255, 24), 1.0))
        painter.setBrush(QColor(18, 24, 33, 26))
        painter.drawRoundedRect(rail_rect, 10, 10)

        badge_size = 18
        gap = 4
        rail_x = rail_rect.left() + 8
        rail_y = rail_rect.top() + 6
        max_x = rail_rect.right() - 8
        bottom_limit = rail_rect.bottom() - badge_size

        review_font = painter.font()
        review_font.setBold(True)
        review_font.setPointSizeF(float(get_review_badge_font_size()))
        painter.setFont(review_font)

        def advance_slot():
            nonlocal rail_x, rail_y
            rail_x += badge_size + gap
            if rail_x + badge_size > max_x:
                rail_x = rail_rect.left() + 8
                rail_y += badge_size + gap

        for spec in get_review_badge_specs():
            if rail_y > bottom_limit:
                break
            self._draw_review_badge(
                painter,
                rail_rect.__class__(rail_x, rail_y, badge_size, badge_size),
                str(spec.label),
                QColor(spec.color),
            )
            advance_slot()

        if rail_y <= bottom_limit:
            self._draw_reaction_badge(
                painter,
                rail_rect.__class__(rail_x, rail_y, badge_size, badge_size),
                'love',
            )
            advance_slot()

        if rail_y <= bottom_limit:
            self._draw_reaction_badge(
                painter,
                rail_rect.__class__(rail_x, rail_y, badge_size, badge_size),
                'bomb',
            )
            advance_slot()

        if rail_y <= bottom_limit:
            style = normalize_thumbnail_star_badge_style(
                settings.value(
                    'thumbnail_star_rating_badge_style',
                    defaultValue='Halo Tag: 3★',
                    type=str,
                )
            )
            spec = get_thumbnail_star_badge_style_spec(style)
            label = self._star_label()
            star_font = painter.font()
            star_font.setBold(True)
            star_font.setPointSizeF(float(spec.get('font_size', 9.0)))
            painter.setFont(star_font)
            fm = painter.fontMetrics()
            value_text = self._star_value_text()
            variant = str(spec.get('variant', 'pill') or 'pill')
            if variant == 'halo':
                halo_diameter = max(16, min(20, int(spec.get('halo_diameter', 18))))
                star_width = int(fm.horizontalAdvance(value_text)) + halo_diameter + int(spec.get('padding_x', 18))
            elif variant == 'split':
                accent_width = max(16, int(spec.get('accent_width', 20)))
                star_width = int(fm.horizontalAdvance(value_text)) + accent_width + int(spec.get('padding_x', 16))
            else:
                star_width = int(fm.horizontalAdvance(label)) + int(spec.get('padding_x', 12))
            star_width = max(26, int(star_width))
            if rail_x + star_width <= max_x:
                self._draw_star_badge(
                    painter,
                    rail_rect.__class__(rail_x, rail_y, star_width, badge_size),
                    label,
                    spec,
                )


class IdeogramOverlayPreviewWidget(QWidget):
    """Live preview of Ideogram overlay label appearance."""

    _SETTINGS_KEYS = {
        'ideogram_overlay_font_size',
        'ideogram_overlay_font_weight',
        'ideogram_overlay_text_outline_px',
        'ideogram_overlay_chip_padding_x',
        'ideogram_overlay_chip_padding_y',
        'ideogram_overlay_border_px',
        'ideogram_overlay_line_halo_px',
        'ideogram_overlay_line_halo_alpha',
        'ideogram_overlay_background_alpha',
        'ideogram_overlay_description_font_size',
        'ideogram_overlay_description_text_alpha',
        'ideogram_overlay_description_background_alpha',
        'ideogram_overlay_text_color',
        'ideogram_overlay_outline_color',
        'ideogram_overlay_background_color',
    }

    _FONT_WEIGHTS = {
        'Normal': QFont.Weight.Normal,
        'Medium': QFont.Weight.Medium,
        'Bold': QFont.Weight.Bold,
        'Black': QFont.Weight.Black,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 190)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._scene = QGraphicsScene(self)
        self._view = QGraphicsView(self._scene, self)
        self._view.setFrameShape(QGraphicsView.Shape.NoFrame)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._view.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self._view.setStyleSheet('background: #11161C; border: 0;')
        layout.addWidget(self._view)
        settings.change.connect(self._on_setting_changed)
        self._rebuild_scene()

    @Slot(str, object)
    def _on_setting_changed(self, key: str, _value):
        if key in self._SETTINGS_KEYS:
            self._rebuild_scene()

    @staticmethod
    def _setting_int(key: str) -> int:
        return int(settings.value(key, defaultValue=DEFAULT_SETTINGS[key], type=int))

    @staticmethod
    def _setting_text(key: str) -> str:
        return str(settings.value(key, defaultValue=DEFAULT_SETTINGS[key], type=str) or DEFAULT_SETTINGS[key])

    @classmethod
    def _setting_color(cls, key: str) -> QColor:
        return QColor(cls._setting_text(key))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rebuild_scene()

    def _rebuild_scene(self):
        self._scene.clear()
        viewport_rect = QRectF(0.0, 0.0, max(280.0, float(self.width())), max(160.0, float(self.height())))
        self._scene.setSceneRect(viewport_rect)
        preview_rect = viewport_rect.adjusted(16.0, 16.0, -16.0, -16.0)

        panel = QGraphicsRectItem(preview_rect)
        panel.setPen(QPen(QColor('#2B3340'), 1.0))
        panel.setBrush(QColor('#1A212B'))
        self._scene.addItem(panel)

        self._draw_preview_region(
            QRectF(preview_rect.left() + 22.0, preview_rect.top() + 36.0, 110.0, 64.0),
            '03 OBJ',
            QColor('#34D6C7'),
        )
        self._draw_preview_region(
            QRectF(preview_rect.left() + 158.0, preview_rect.top() + 58.0, 112.0, 52.0),
            '04 TEXT',
            QColor('#FFB454'),
        )
        self._view.fitInView(preview_rect.adjusted(-8.0, -8.0, 8.0, 8.0), Qt.AspectRatioMode.KeepAspectRatio)

    def _draw_preview_region(self, rect: QRectF, text: str, accent: QColor):
        border_width = max(1.0, float(self._setting_int('ideogram_overlay_border_px')))
        fill = QColor(accent)
        fill.setAlpha(28)

        region = QGraphicsRectItem(rect)
        halo_width = max(0.0, float(self._setting_int('ideogram_overlay_line_halo_px')))
        halo = QColor('#FFFFFF' if accent.lightness() < 128 else '#05070A')
        halo.setAlpha(max(0, min(255, self._setting_int('ideogram_overlay_line_halo_alpha'))))
        region.setPen(QPen(halo, border_width + halo_width, Qt.PenStyle.SolidLine))
        region.setBrush(fill)
        self._scene.addItem(region)

        strip_height = min(10.0, max(2.0, rect.height() * 0.16))
        strip = QGraphicsRectItem(
            QRectF(rect.left(), rect.top(), rect.width(), strip_height)
        )
        strip.setPen(QPen(Qt.PenStyle.NoPen))
        strip.setBrush(accent)
        self._scene.addItem(strip)

        desc_rect = rect.adjusted(6.0, strip_height + 6.0, -6.0, -6.0)
        desc_background = QGraphicsRectItem(desc_rect.adjusted(-4.0, -3.0, 4.0, 3.0))
        desc_background.setPen(QPen(Qt.PenStyle.NoPen))
        desc_brush = QColor('#05070A')
        desc_brush.setAlpha(
            max(
                0,
                min(
                    255,
                    self._setting_int(
                        'ideogram_overlay_description_background_alpha'
                    ),
                ),
            )
        )
        desc_background.setBrush(desc_brush)
        self._scene.addItem(desc_background)

        desc_text = QGraphicsTextItem(
            'OBJ: weathered bridge tower with concrete texture'
            if 'OBJ' in text
            else 'TEXT: readable sign on the wall'
        )
        desc_text.setTextWidth(desc_rect.width())
        desc_font = QFont()
        desc_font.setPointSize(
            self._setting_int('ideogram_overlay_description_font_size')
        )
        desc_font.setWeight(QFont.Weight.DemiBold)
        desc_text.setFont(desc_font)
        desc_color = self._setting_color('ideogram_overlay_text_color')
        desc_color.setAlpha(
            max(
                0,
                min(
                    255,
                    self._setting_int('ideogram_overlay_description_text_alpha'),
                ),
            )
        )
        desc_text.setDefaultTextColor(desc_color)
        desc_text.setPos(desc_rect.topLeft())
        self._scene.addItem(desc_text)

        inner = QGraphicsRectItem(rect)
        inner.setPen(QPen(accent, border_width, Qt.PenStyle.SolidLine))
        inner.setBrush(Qt.BrushStyle.NoBrush)
        self._scene.addItem(inner)
        self._add_label_chip(rect.left() + 3.0, rect.top() + 3.0, text, accent)

    def _add_label_chip(self, x: float, y: float, text: str, accent: QColor):
        label = IdeogramLabelItem(text, accent)
        label.setPos(x, y)
        self._scene.addItem(label)


class SettingsDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle('Settings')

        # Main layout for dialog
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # Create tab widget
        tab_widget = QTabWidget()
        main_layout.addWidget(tab_widget)

        # Create tabs
        tab_widget.addTab(self._create_general_tab(), 'General')
        tab_widget.addTab(self._create_badges_tab(), 'Badges')
        tab_widget.addTab(self._create_ideogram_tab(), 'Ideogram')
        tab_widget.addTab(self._create_models_tab(), 'Models')
        tab_widget.addTab(self._create_cache_tab(), 'Cache')
        tab_widget.addTab(self._create_spell_check_tab(), 'Spell Check')
        tab_widget.addTab(self._create_advanced_tab(), 'Advanced')

        # Restore last selected tab
        last_tab = settings.value('settings_dialog_last_tab', defaultValue=0, type=int)
        if 0 <= last_tab < tab_widget.count():
            tab_widget.setCurrentIndex(last_tab)

        # Save tab index when changed
        tab_widget.currentChanged.connect(
            lambda index: settings.setValue('settings_dialog_last_tab', index)
        )

        # Restart warning at bottom of main dialog
        self.restart_warning = ('Restart the application to apply the new '
                                'settings.')
        self.warning_label = QLabel(self.restart_warning)
        self.warning_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.warning_label.setStyleSheet('color: red;')
        main_layout.addWidget(self.warning_label)

        # Keep the dialog resizable and clamp its initial size to the current screen.
        # Each tab already lives inside a scroll area, so smaller screens should scroll
        # instead of clipping the whole settings window off-screen.
        self._apply_initial_dialog_size()
        self.warning_label.hide()

    def closeEvent(self, event):
        repair_thread = getattr(self, '_extensionless_repair_thread', None)
        if repair_thread is not None and repair_thread.isRunning():
            QMessageBox.information(
                self,
                'Scan Still Running',
                'Cancel the extensionless image scan before closing Settings.'
            )
            event.ignore()
            return
        super().closeEvent(event)

    def _settings_screen(self):
        parent = self.parentWidget()
        if parent is not None:
            window_handle = parent.windowHandle()
            if window_handle is not None and window_handle.screen() is not None:
                return window_handle.screen()
            if parent.screen() is not None:
                return parent.screen()
        if self.screen() is not None:
            return self.screen()
        return QApplication.primaryScreen()

    def _apply_initial_dialog_size(self):
        size_hint = self.sizeHint()
        screen = self._settings_screen()
        if screen is None:
            self.resize(size_hint)
            return

        available = screen.availableGeometry()
        max_width = min(available.width(), max(420, int(available.width() * 0.92)))
        max_height = min(available.height(), max(360, int(available.height() * 0.9)))
        min_width = min(max_width, 720)
        min_height = min(max_height, 520)

        self.setMinimumSize(min_width, min_height)
        self.resize(
            min(max(size_hint.width(), min_width), max_width),
            min(max(size_hint.height(), min_height), max_height),
        )

    def _create_general_tab(self):
        """Create General settings tab."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        grid_layout = QGridLayout()

        # Font size
        grid_layout.addWidget(QLabel('Font size (pt)'), 0, 0,
                              Qt.AlignmentFlag.AlignRight)
        font_size_spin_box = SettingsSpinBox(
            key='font_size',
            minimum=1, maximum=99)
        font_size_spin_box.valueChanged.connect(self.show_restart_warning)
        grid_layout.addWidget(font_size_spin_box, 0, 1,
                              Qt.AlignmentFlag.AlignLeft)

        # File types
        grid_layout.addWidget(QLabel('File types to show in image list'), 1, 0,
                              Qt.AlignmentFlag.AlignRight)
        file_types_line_edit = SettingsLineEdit(
            key='image_list_file_formats')
        file_types_line_edit.setMinimumWidth(400)
        file_types_line_edit.textChanged.connect(self.show_restart_warning)
        grid_layout.addWidget(file_types_line_edit, 1, 1,
                              Qt.AlignmentFlag.AlignLeft)

        # Image width
        grid_layout.addWidget(QLabel('Image width in image list (px)'), 2, 0,
                              Qt.AlignmentFlag.AlignRight)
        image_list_image_width_spin_box = SettingsSpinBox(
            key='image_list_image_width',
            minimum=16, maximum=9999)
        image_list_image_width_spin_box.valueChanged.connect(
            self.show_restart_warning)
        grid_layout.addWidget(image_list_image_width_spin_box, 2, 1,
                              Qt.AlignmentFlag.AlignLeft)

        # Insert space after separator (create first, needed by tag separator handler)
        grid_layout.addWidget(QLabel('Insert space after tag separator'), 4, 0,
                              Qt.AlignmentFlag.AlignRight)
        self.insert_space_after_tag_separator_check_box = SettingsBigCheckBox(
            key='insert_space_after_tag_separator')
        self.insert_space_after_tag_separator_check_box.stateChanged.connect(
            self.show_restart_warning)
        grid_layout.addWidget(self.insert_space_after_tag_separator_check_box,
                              4, 1, Qt.AlignmentFlag.AlignLeft)

        # Tag separator (must be after checkbox creation)
        grid_layout.addWidget(QLabel('Tag separator (\\n for newline)'), 3, 0,
                              Qt.AlignmentFlag.AlignRight)
        tag_separator_line_edit = QLineEdit()
        tag_separator = settings.value(
            'tag_separator', defaultValue=DEFAULT_SETTINGS['tag_separator'],
            type=str)
        if tag_separator == '\n':
            tag_separator = r'\n'
            self.disable_insert_space_after_tag_separator_check_box()
        tag_separator_line_edit.setMaximumWidth(50)
        tag_separator_line_edit.setText(tag_separator)
        tag_separator_line_edit.textChanged.connect(
            self.handle_tag_separator_change)
        grid_layout.addWidget(tag_separator_line_edit, 3, 1,
                              Qt.AlignmentFlag.AlignLeft)

        # Autocomplete
        grid_layout.addWidget(QLabel('Show tag autocomplete suggestions'),
                              5, 0, Qt.AlignmentFlag.AlignRight)
        autocomplete_tags_check_box = SettingsBigCheckBox(
            key='autocomplete_tags')
        autocomplete_tags_check_box.stateChanged.connect(
            self.show_restart_warning)
        grid_layout.addWidget(autocomplete_tags_check_box, 5, 1,
                              Qt.AlignmentFlag.AlignLeft)

        # Pagination threshold
        grid_layout.addWidget(QLabel('Paginate folders larger than (images)'), 6, 0,
                              Qt.AlignmentFlag.AlignRight)
        pagination_spin_box = SettingsSpinBox(
            key='pagination_threshold',
            minimum=0, maximum=100000)
        pagination_spin_box.setToolTip(
            'Enable pagination mode for folders with more than this many images.\n\n'
            'Pagination mode loads thumbnails on-demand as you scroll, keeping only\n'
            'visible + nearby thumbnails in memory. This enables smooth scrolling\n'
            'with datasets of any size (even 1M+ images).\n\n'
            'Setting this to 0 (recommended):\n'
            'Always use pagination mode for consistent performance regardless of folder size.\n'
            'Pagination is now highly optimized with low-priority background saves and\n'
            'minimal overhead - it works smoothly even for small folders.\n\n'
            'Setting this higher (e.g., 500, 1000, 5000):\n'
            'Only paginate when folders exceed this size. Smaller folders will load\n'
            'all thumbnails at once (classic mode). This may cause UI freezes and\n'
            'memory issues with large folders if threshold is set too high.')
        pagination_spin_box.valueChanged.connect(self.show_restart_warning)
        grid_layout.addWidget(pagination_spin_box, 6, 1,
                              Qt.AlignmentFlag.AlignLeft)

        # Thumbnail eviction pages (VRAM behavior in paginated mode)
        grid_layout.addWidget(QLabel('Thumbnail eviction pages (VRAM)'), 7, 0,
                              Qt.AlignmentFlag.AlignRight)
        eviction_pages_spin_box = SettingsSpinBox(
            key='thumbnail_eviction_pages',
            minimum=1, maximum=5)
        eviction_pages_spin_box.setToolTip(
            'How many pages around the viewport keep thumbnails resident.\n'
            '1 = lower VRAM, more refill/pop-in\n'
            '3 = balanced default\n'
            '5 = higher VRAM, smoother revisits\n'
            'Applied live.')
        grid_layout.addWidget(eviction_pages_spin_box, 7, 1,
                              Qt.AlignmentFlag.AlignLeft)

        # Max pages in memory (page object budget for paginated mode)
        grid_layout.addWidget(QLabel('Max pages in memory (RAM)'), 8, 0,
                              Qt.AlignmentFlag.AlignRight)
        max_pages_spin_box = SettingsSpinBox(
            key='max_pages_in_memory',
            minimum=3, maximum=60, default=20)
        max_pages_spin_box.setToolTip(
            'Maximum paginated pages kept in RAM.\n'
            'Lower = less RAM, more refetch on jumps\n'
            'Higher = smoother revisits, more RAM use\n'
            'Guardrail: effective value is at least (2 * eviction pages + 1).\n'
            'Applied live.')
        grid_layout.addWidget(max_pages_spin_box, 8, 1,
                              Qt.AlignmentFlag.AlignLeft)

        # Video player skin
        grid_layout.addWidget(QLabel('Video player skin'), 9, 0,
                              Qt.AlignmentFlag.AlignRight)
        self.video_skin_combo = SettingsComboBox(
            key='video_player_skin',
            default='Classic')

        # Populate with available skins
        from skins.engine import SkinManager
        skin_manager = SkinManager()
        available_skins = skin_manager.get_available_skins()
        skin_names = [skin['name'] for skin in available_skins]
        if skin_names:
            self.video_skin_combo.addItems(skin_names)
        else:
            self.video_skin_combo.addItem('Modern Dark')  # Fallback

        self.video_skin_combo.setToolTip(
            'Choose visual theme for video player controls.\n\n'
            'Skins change colors, spacing, and appearance of:\n'
            '- Control bar and buttons\n'
            '- Timeline slider and loop markers\n'
            '- Speed slider gradient\n\n'
            'Changes apply instantly when you switch skins.\n'
            'Create custom skins in taggui/skins/user/ folder.')

        # Apply skin changes immediately (no restart needed!)
        self.video_skin_combo.currentTextChanged.connect(self._on_skin_changed)

        grid_layout.addWidget(self.video_skin_combo, 10, 1,
                              Qt.AlignmentFlag.AlignLeft)

        layout.addLayout(grid_layout)
        layout.addStretch()

        scroll_area.setWidget(widget)
        return scroll_area

    def _create_badges_tab(self):
        """Create review badge customization tab."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        thumbnail_group = QGroupBox('Thumbnail Overlays')
        thumbnail_group_layout = QHBoxLayout(thumbnail_group)
        thumbnail_group_layout.setContentsMargins(12, 12, 12, 12)
        thumbnail_group_layout.setSpacing(18)

        controls_widget = QWidget()
        thumbnail_layout = QGridLayout(controls_widget)
        thumbnail_layout.setContentsMargins(0, 0, 0, 0)
        thumbnail_layout.setHorizontalSpacing(12)
        thumbnail_layout.setVerticalSpacing(10)

        thumbnail_layout.addWidget(QLabel('Show review badges'), 0, 0, Qt.AlignmentFlag.AlignRight)
        thumbnail_layout.addWidget(
            SettingsBigCheckBox(
                key='thumbnail_show_review_badges',
                text='Enabled',
            ),
            0,
            1,
            Qt.AlignmentFlag.AlignLeft,
        )

        thumbnail_layout.addWidget(QLabel('Review style'), 0, 2, Qt.AlignmentFlag.AlignRight)
        review_style_combo = SettingsComboBox(
            key='thumbnail_review_badge_style',
            default='Review Tile',
        )
        review_style_combo.addItems([label for _key, label in THUMBNAIL_BADGE_STYLE_OPTIONS])
        review_style_combo.setMinimumWidth(180)
        thumbnail_layout.addWidget(review_style_combo, 0, 3, Qt.AlignmentFlag.AlignLeft)

        thumbnail_layout.addWidget(QLabel('Show reaction badges'), 1, 0, Qt.AlignmentFlag.AlignRight)
        thumbnail_layout.addWidget(
            SettingsBigCheckBox(
                key='thumbnail_show_reaction_badges',
                text='Enabled',
            ),
            1,
            1,
            Qt.AlignmentFlag.AlignLeft,
        )

        thumbnail_layout.addWidget(QLabel('Reaction side'), 1, 2, Qt.AlignmentFlag.AlignRight)
        reaction_position_combo = SettingsComboBox(
            key='thumbnail_reaction_badge_position',
            default='Left',
        )
        reaction_position_combo.addItems(['Left', 'Right'])
        thumbnail_layout.addWidget(reaction_position_combo, 1, 3, Qt.AlignmentFlag.AlignLeft)

        thumbnail_layout.addWidget(QLabel('Reaction style'), 2, 0, Qt.AlignmentFlag.AlignRight)
        reaction_style_combo = SettingsComboBox(
            key='thumbnail_reaction_badge_style',
            default='Review Tile',
        )
        reaction_style_combo.addItems([label for _key, label in THUMBNAIL_BADGE_STYLE_OPTIONS])
        reaction_style_combo.setMinimumWidth(180)
        thumbnail_layout.addWidget(reaction_style_combo, 2, 1, 1, 3, Qt.AlignmentFlag.AlignLeft)

        thumbnail_layout.addWidget(QLabel('Show star badge'), 3, 0, Qt.AlignmentFlag.AlignRight)
        thumbnail_layout.addWidget(
            SettingsBigCheckBox(
                key='thumbnail_show_star_rating_badge',
                text='Enabled',
            ),
            3,
            1,
            Qt.AlignmentFlag.AlignLeft,
        )

        thumbnail_layout.addWidget(QLabel('Star side'), 3, 2, Qt.AlignmentFlag.AlignRight)
        star_position_combo = SettingsComboBox(
            key='thumbnail_star_rating_badge_position',
            default='Right',
        )
        star_position_combo.addItems(['Left', 'Right'])
        thumbnail_layout.addWidget(star_position_combo, 3, 3, Qt.AlignmentFlag.AlignLeft)

        thumbnail_layout.addWidget(QLabel('Star style'), 4, 0, Qt.AlignmentFlag.AlignRight)
        star_style_combo = SettingsComboBox(
            key='thumbnail_star_rating_badge_style',
            default='Halo Tag: 3★',
        )
        star_style_combo.addItems([label for _key, label in THUMBNAIL_STAR_BADGE_STYLE_OPTIONS])
        star_style_combo.setMinimumWidth(220)
        thumbnail_layout.addWidget(star_style_combo, 4, 1, 1, 3, Qt.AlignmentFlag.AlignLeft)

        thumbnail_group_layout.addWidget(controls_widget, 1)
        thumbnail_preview = ThumbnailOverlayPreviewWidget(self)
        thumbnail_group_layout.addWidget(thumbnail_preview, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(thumbnail_group)

        appearance_grid = QGridLayout()
        appearance_grid.setHorizontalSpacing(10)
        appearance_grid.addWidget(QLabel('Text color'), 0, 0, Qt.AlignmentFlag.AlignRight)
        self.review_badge_text_color_button = QPushButton()
        self._review_badge_text_color = settings.value('review_badge_text_color', '#FFFFFF', type=str)
        self._apply_badge_color_button_style(self.review_badge_text_color_button, self._review_badge_text_color)
        self.review_badge_text_color_button.clicked.connect(self._pick_review_badge_text_color)
        appearance_grid.addWidget(self.review_badge_text_color_button, 0, 1, Qt.AlignmentFlag.AlignLeft)

        appearance_grid.addWidget(QLabel('Font size'), 0, 2, Qt.AlignmentFlag.AlignRight)
        self.review_badge_font_size_combo = SettingsComboBox(
            key='review_badge_font_size',
            default='9',
        )
        self.review_badge_font_size_combo.addItems([str(size) for size in range(8, 17)])
        self.review_badge_font_size_combo.currentTextChanged.connect(self._save_review_badge_appearance_settings)
        appearance_grid.addWidget(self.review_badge_font_size_combo, 0, 3, Qt.AlignmentFlag.AlignLeft)

        appearance_grid.addWidget(QLabel('Corner roundness'), 0, 4, Qt.AlignmentFlag.AlignRight)
        self.review_badge_corner_radius_combo = SettingsComboBox(
            key='review_badge_corner_radius',
            default='5',
        )
        self.review_badge_corner_radius_combo.addItems([str(size) for size in range(2, 15)])
        self.review_badge_corner_radius_combo.currentTextChanged.connect(self._save_review_badge_appearance_settings)
        appearance_grid.addWidget(self.review_badge_corner_radius_combo, 0, 5, Qt.AlignmentFlag.AlignLeft)
        layout.addLayout(appearance_grid)

        header = QGridLayout()
        header.setHorizontalSpacing(10)
        header.addWidget(QLabel('Slot'), 0, 0)
        header.addWidget(QLabel('Label'), 0, 1)
        header.addWidget(QLabel('Tooltip'), 0, 2)
        header.addWidget(QLabel('Color'), 0, 3)
        header.addWidget(QLabel('Shortcut(s)'), 0, 4)
        layout.addLayout(header)

        self._review_badge_editors = []
        rows_layout = QGridLayout()
        rows_layout.setHorizontalSpacing(10)
        rows_layout.setVerticalSpacing(8)

        for row_index, spec in enumerate(get_review_badge_specs(), start=1):
            slot_label = QLabel(self._badge_slot_title(spec))
            symbol_edit = QLineEdit(spec.label)
            symbol_edit.setMaxLength(4)
            symbol_edit.setMaximumWidth(60)

            tooltip_edit = QLineEdit(spec.title)
            tooltip_edit.setPlaceholderText('Optional hover title')
            tooltip_edit.setMinimumWidth(200)

            color_button = QPushButton(spec.color)
            color_button.setMaximumWidth(96)
            self._apply_badge_color_button_style(color_button, spec.color)

            shortcuts_edit = QLineEdit(', '.join(spec.shortcuts))
            shortcuts_edit.setPlaceholderText('Comma-separated shortcuts')
            shortcuts_edit.setMinimumWidth(220)

            rows_layout.addWidget(slot_label, row_index, 0)
            rows_layout.addWidget(symbol_edit, row_index, 1)
            rows_layout.addWidget(tooltip_edit, row_index, 2)
            rows_layout.addWidget(color_button, row_index, 3)
            rows_layout.addWidget(shortcuts_edit, row_index, 4)

            entry = {
                'badge_id': spec.badge_id,
                'symbol_edit': symbol_edit,
                'tooltip_edit': tooltip_edit,
                'color_button': color_button,
                'shortcuts_edit': shortcuts_edit,
                'color': spec.color,
            }
            self._review_badge_editors.append(entry)

            symbol_edit.textChanged.connect(self._save_review_badge_schema_settings)
            tooltip_edit.textChanged.connect(self._save_review_badge_schema_settings)
            shortcuts_edit.textChanged.connect(self._save_review_badge_schema_settings)
            color_button.clicked.connect(
                lambda _checked=False, current_entry=entry: self._pick_review_badge_color(current_entry)
            )

        layout.addLayout(rows_layout)

        reset_button = QPushButton('Reset Badge Defaults')
        reset_button.clicked.connect(self._reset_review_badge_schema_settings)
        layout.addWidget(reset_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()

        scroll_area.setWidget(widget)
        return scroll_area

    @staticmethod
    def _badge_slot_title(spec) -> str:
        if spec.kind == 'rank':
            return f'Rank {int(spec.rank or 0)}'
        return str(spec.flag_name or spec.badge_id).replace('_', ' ').title()

    @staticmethod
    def _apply_badge_color_button_style(button: QPushButton, color_hex: str):
        button.setText(color_hex)
        button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {color_hex};
                color: #111827;
                border: 1px solid rgba(15, 23, 42, 0.28);
                border-radius: 4px;
                padding: 4px 8px;
                font-weight: 700;
            }}
            """
        )

    def _pick_review_badge_color(self, entry: dict):
        selected_color = QColorDialog.getColor(parent=self)
        if not selected_color.isValid():
            return
        color_hex = selected_color.name().upper()
        entry['color'] = color_hex
        self._apply_badge_color_button_style(entry['color_button'], color_hex)
        self._save_review_badge_schema_settings()

    def _collect_review_badge_schema_rows(self) -> list[dict]:
        rows = []
        for entry in getattr(self, '_review_badge_editors', []):
            rows.append(
                {
                    'badge_id': entry['badge_id'],
                    'label': entry['symbol_edit'].text(),
                    'title': entry['tooltip_edit'].text(),
                    'color': entry.get('color', ''),
                    'shortcuts': entry['shortcuts_edit'].text(),
                }
            )
        return rows

    def _save_review_badge_schema_settings(self, *_args):
        save_review_badge_schema(self._collect_review_badge_schema_rows())

    def _pick_review_badge_text_color(self):
        selected_color = QColorDialog.getColor(parent=self)
        if not selected_color.isValid():
            return
        self._review_badge_text_color = selected_color.name().upper()
        self._apply_badge_color_button_style(
            self.review_badge_text_color_button,
            self._review_badge_text_color,
        )
        self._save_review_badge_appearance_settings()

    def _save_review_badge_appearance_settings(self, *_args):
        settings.setValue('review_badge_text_color', self._review_badge_text_color)
        settings.setValue('review_badge_font_size', self.review_badge_font_size_combo.currentText())
        settings.setValue('review_badge_corner_radius', self.review_badge_corner_radius_combo.currentText())

    def _reset_review_badge_schema_settings(self):
        reset_review_badge_schema()
        self._review_badge_text_color = '#FFFFFF'
        self._apply_badge_color_button_style(
            self.review_badge_text_color_button,
            self._review_badge_text_color,
        )
        self.review_badge_font_size_combo.setCurrentText('9')
        self.review_badge_corner_radius_combo.setCurrentText('5')
        self._save_review_badge_appearance_settings()
        specs = get_review_badge_specs()
        spec_map = {spec.badge_id: spec for spec in specs}
        for entry in getattr(self, '_review_badge_editors', []):
            spec = spec_map.get(entry['badge_id'])
            if spec is None:
                continue
            entry['symbol_edit'].setText(spec.label)
            entry['tooltip_edit'].setText(spec.title)
            entry['shortcuts_edit'].setText(', '.join(spec.shortcuts))
            entry['color'] = spec.color
            self._apply_badge_color_button_style(entry['color_button'], spec.color)

    def _create_ideogram_tab(self):
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(18)

        preview_group = QGroupBox('Overlay Preview')
        preview_layout = QVBoxLayout(preview_group)
        preview_layout.setContentsMargins(14, 14, 14, 14)
        preview_layout.setSpacing(10)
        preview_layout.addWidget(IdeogramOverlayPreviewWidget(self), 0, Qt.AlignmentFlag.AlignTop)
        preview_note = QLabel('Changes apply live to the preview and to Ideogram overlays in the main viewer.')
        preview_note.setWordWrap(True)
        preview_layout.addWidget(preview_note)
        layout.addWidget(preview_group)

        controls_group = QGroupBox('Label Style')
        controls_layout = QGridLayout(controls_group)
        controls_layout.setHorizontalSpacing(12)
        controls_layout.setVerticalSpacing(10)

        font_size_spin = SettingsSpinBox(
            key='ideogram_overlay_font_size',
            minimum=6,
            maximum=28,
            default=DEFAULT_SETTINGS['ideogram_overlay_font_size'],
        )
        font_weight_combo = SettingsComboBox(
            key='ideogram_overlay_font_weight',
            default=DEFAULT_SETTINGS['ideogram_overlay_font_weight'],
        )
        font_weight_combo.addItems(['Normal', 'Medium', 'Bold', 'Black'])
        outline_width_spin = SettingsSpinBox(
            key='ideogram_overlay_text_outline_px',
            minimum=0,
            maximum=8,
            default=DEFAULT_SETTINGS['ideogram_overlay_text_outline_px'],
        )
        border_width_spin = SettingsSpinBox(
            key='ideogram_overlay_border_px',
            minimum=1,
            maximum=8,
            default=DEFAULT_SETTINGS['ideogram_overlay_border_px'],
        )
        halo_width_spin = SettingsSpinBox(
            key='ideogram_overlay_line_halo_px',
            minimum=0,
            maximum=8,
            default=DEFAULT_SETTINGS['ideogram_overlay_line_halo_px'],
        )
        halo_alpha_slider = SettingsSlider(
            key='ideogram_overlay_line_halo_alpha',
            minimum=0,
            maximum=255,
            default=DEFAULT_SETTINGS['ideogram_overlay_line_halo_alpha'],
        )
        halo_alpha_value_label = QLabel(str(halo_alpha_slider.value()))
        halo_alpha_slider.valueChanged.connect(
            lambda value: halo_alpha_value_label.setText(str(int(value)))
        )
        padding_x_spin = SettingsSpinBox(
            key='ideogram_overlay_chip_padding_x',
            minimum=1,
            maximum=20,
            default=DEFAULT_SETTINGS['ideogram_overlay_chip_padding_x'],
        )
        padding_y_spin = SettingsSpinBox(
            key='ideogram_overlay_chip_padding_y',
            minimum=1,
            maximum=16,
            default=DEFAULT_SETTINGS['ideogram_overlay_chip_padding_y'],
        )
        alpha_slider = SettingsSlider(
            key='ideogram_overlay_background_alpha',
            minimum=0,
            maximum=255,
            default=DEFAULT_SETTINGS['ideogram_overlay_background_alpha'],
        )
        alpha_value_label = QLabel(str(alpha_slider.value()))
        alpha_slider.valueChanged.connect(lambda value: alpha_value_label.setText(str(int(value))))
        desc_font_size_spin = SettingsSpinBox(
            key='ideogram_overlay_description_font_size',
            minimum=6,
            maximum=24,
            default=DEFAULT_SETTINGS['ideogram_overlay_description_font_size'],
        )
        desc_text_alpha_slider = SettingsSlider(
            key='ideogram_overlay_description_text_alpha',
            minimum=0,
            maximum=255,
            default=DEFAULT_SETTINGS['ideogram_overlay_description_text_alpha'],
        )
        desc_text_alpha_value_label = QLabel(str(desc_text_alpha_slider.value()))
        desc_text_alpha_slider.valueChanged.connect(
            lambda value: desc_text_alpha_value_label.setText(str(int(value)))
        )
        desc_background_alpha_slider = SettingsSlider(
            key='ideogram_overlay_description_background_alpha',
            minimum=0,
            maximum=255,
            default=DEFAULT_SETTINGS[
                'ideogram_overlay_description_background_alpha'
            ],
        )
        desc_background_alpha_value_label = QLabel(
            str(desc_background_alpha_slider.value())
        )
        desc_background_alpha_slider.valueChanged.connect(
            lambda value: desc_background_alpha_value_label.setText(str(int(value)))
        )

        controls_layout.addWidget(QLabel('Font size'), 0, 0, Qt.AlignmentFlag.AlignRight)
        controls_layout.addWidget(font_size_spin, 0, 1)
        controls_layout.addWidget(QLabel('Font weight'), 0, 2, Qt.AlignmentFlag.AlignRight)
        controls_layout.addWidget(font_weight_combo, 0, 3)

        controls_layout.addWidget(QLabel('Text outline'), 1, 0, Qt.AlignmentFlag.AlignRight)
        controls_layout.addWidget(outline_width_spin, 1, 1)
        controls_layout.addWidget(QLabel('Line width'), 1, 2, Qt.AlignmentFlag.AlignRight)
        controls_layout.addWidget(border_width_spin, 1, 3)

        controls_layout.addWidget(QLabel('Line halo'), 2, 0, Qt.AlignmentFlag.AlignRight)
        controls_layout.addWidget(halo_width_spin, 2, 1)
        controls_layout.addWidget(QLabel('Halo alpha'), 2, 2, Qt.AlignmentFlag.AlignRight)
        controls_layout.addWidget(halo_alpha_slider, 2, 3)
        controls_layout.addWidget(halo_alpha_value_label, 2, 4, Qt.AlignmentFlag.AlignLeft)

        controls_layout.addWidget(QLabel('Horizontal padding'), 3, 0, Qt.AlignmentFlag.AlignRight)
        controls_layout.addWidget(padding_x_spin, 3, 1)
        controls_layout.addWidget(QLabel('Vertical padding'), 3, 2, Qt.AlignmentFlag.AlignRight)
        controls_layout.addWidget(padding_y_spin, 3, 3)

        controls_layout.addWidget(QLabel('Background alpha'), 4, 0, Qt.AlignmentFlag.AlignRight)
        controls_layout.addWidget(alpha_slider, 4, 1, 1, 2)
        controls_layout.addWidget(alpha_value_label, 4, 3, Qt.AlignmentFlag.AlignLeft)

        controls_layout.addWidget(QLabel('Box text size'), 5, 0, Qt.AlignmentFlag.AlignRight)
        controls_layout.addWidget(desc_font_size_spin, 5, 1)
        controls_layout.addWidget(QLabel('Box text alpha'), 5, 2, Qt.AlignmentFlag.AlignRight)
        controls_layout.addWidget(desc_text_alpha_slider, 5, 3)
        controls_layout.addWidget(desc_text_alpha_value_label, 5, 4, Qt.AlignmentFlag.AlignLeft)

        controls_layout.addWidget(QLabel('Box fill alpha'), 6, 0, Qt.AlignmentFlag.AlignRight)
        controls_layout.addWidget(desc_background_alpha_slider, 6, 1, 1, 2)
        controls_layout.addWidget(desc_background_alpha_value_label, 6, 3, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(controls_group)

        colors_group = QGroupBox('Colors')
        colors_layout = QGridLayout(colors_group)
        colors_layout.setHorizontalSpacing(12)
        colors_layout.setVerticalSpacing(10)

        self._ideogram_text_color = settings.value(
            'ideogram_overlay_text_color',
            DEFAULT_SETTINGS['ideogram_overlay_text_color'],
            type=str,
        )
        self._ideogram_outline_color = settings.value(
            'ideogram_overlay_outline_color',
            DEFAULT_SETTINGS['ideogram_overlay_outline_color'],
            type=str,
        )
        self._ideogram_background_color = settings.value(
            'ideogram_overlay_background_color',
            DEFAULT_SETTINGS['ideogram_overlay_background_color'],
            type=str,
        )

        self.ideogram_text_color_button = QPushButton()
        self.ideogram_outline_color_button = QPushButton()
        self.ideogram_background_color_button = QPushButton()
        self._apply_badge_color_button_style(self.ideogram_text_color_button, self._ideogram_text_color)
        self._apply_badge_color_button_style(self.ideogram_outline_color_button, self._ideogram_outline_color)
        self._apply_badge_color_button_style(self.ideogram_background_color_button, self._ideogram_background_color)
        self.ideogram_text_color_button.clicked.connect(lambda: self._pick_ideogram_color('text'))
        self.ideogram_outline_color_button.clicked.connect(lambda: self._pick_ideogram_color('outline'))
        self.ideogram_background_color_button.clicked.connect(lambda: self._pick_ideogram_color('background'))

        colors_layout.addWidget(QLabel('Text color'), 0, 0, Qt.AlignmentFlag.AlignRight)
        colors_layout.addWidget(self.ideogram_text_color_button, 0, 1)
        colors_layout.addWidget(QLabel('Outline color'), 0, 2, Qt.AlignmentFlag.AlignRight)
        colors_layout.addWidget(self.ideogram_outline_color_button, 0, 3)
        colors_layout.addWidget(QLabel('Background color'), 1, 0, Qt.AlignmentFlag.AlignRight)
        colors_layout.addWidget(self.ideogram_background_color_button, 1, 1)
        layout.addWidget(colors_group)

        reset_button = QPushButton('Reset Ideogram Label Defaults')
        reset_button.clicked.connect(self._reset_ideogram_overlay_settings)
        layout.addWidget(reset_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()

        scroll_area.setWidget(widget)
        return scroll_area

    def _pick_ideogram_color(self, role: str):
        selected_color = QColorDialog.getColor(parent=self)
        if not selected_color.isValid():
            return
        color_hex = selected_color.name().upper()
        if role == 'text':
            self._ideogram_text_color = color_hex
            self._apply_badge_color_button_style(self.ideogram_text_color_button, color_hex)
            settings.setValue('ideogram_overlay_text_color', color_hex)
            return
        if role == 'outline':
            self._ideogram_outline_color = color_hex
            self._apply_badge_color_button_style(self.ideogram_outline_color_button, color_hex)
            settings.setValue('ideogram_overlay_outline_color', color_hex)
            return
        self._ideogram_background_color = color_hex
        self._apply_badge_color_button_style(self.ideogram_background_color_button, color_hex)
        settings.setValue('ideogram_overlay_background_color', color_hex)

    def _reset_ideogram_overlay_settings(self):
        reset_values = {
            'ideogram_overlay_font_size': DEFAULT_SETTINGS['ideogram_overlay_font_size'],
            'ideogram_overlay_font_weight': DEFAULT_SETTINGS['ideogram_overlay_font_weight'],
            'ideogram_overlay_text_outline_px': DEFAULT_SETTINGS['ideogram_overlay_text_outline_px'],
            'ideogram_overlay_chip_padding_x': DEFAULT_SETTINGS['ideogram_overlay_chip_padding_x'],
            'ideogram_overlay_chip_padding_y': DEFAULT_SETTINGS['ideogram_overlay_chip_padding_y'],
            'ideogram_overlay_border_px': DEFAULT_SETTINGS['ideogram_overlay_border_px'],
            'ideogram_overlay_line_halo_px': DEFAULT_SETTINGS['ideogram_overlay_line_halo_px'],
            'ideogram_overlay_line_halo_alpha': DEFAULT_SETTINGS['ideogram_overlay_line_halo_alpha'],
            'ideogram_overlay_background_alpha': DEFAULT_SETTINGS['ideogram_overlay_background_alpha'],
            'ideogram_overlay_description_font_size': DEFAULT_SETTINGS['ideogram_overlay_description_font_size'],
            'ideogram_overlay_description_text_alpha': DEFAULT_SETTINGS['ideogram_overlay_description_text_alpha'],
            'ideogram_overlay_description_background_alpha': DEFAULT_SETTINGS['ideogram_overlay_description_background_alpha'],
            'ideogram_overlay_text_color': DEFAULT_SETTINGS['ideogram_overlay_text_color'],
            'ideogram_overlay_outline_color': DEFAULT_SETTINGS['ideogram_overlay_outline_color'],
            'ideogram_overlay_background_color': DEFAULT_SETTINGS['ideogram_overlay_background_color'],
        }
        for key, value in reset_values.items():
            settings.setValue(key, value)
        self._ideogram_text_color = reset_values['ideogram_overlay_text_color']
        self._ideogram_outline_color = reset_values['ideogram_overlay_outline_color']
        self._ideogram_background_color = reset_values['ideogram_overlay_background_color']
        self._apply_badge_color_button_style(self.ideogram_text_color_button, self._ideogram_text_color)
        self._apply_badge_color_button_style(self.ideogram_outline_color_button, self._ideogram_outline_color)
        self._apply_badge_color_button_style(self.ideogram_background_color_button, self._ideogram_background_color)

    def _create_models_tab(self):
        """Create Models settings tab."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        grid_layout = QGridLayout()

        # Auto-captioning models directory
        grid_layout.addWidget(QLabel('Auto-captioning models directory'), 0, 0,
                              Qt.AlignmentFlag.AlignRight)
        self.models_directory_line_edit = SettingsLineEdit(
            key='models_directory_path')
        self.models_directory_line_edit.setMinimumWidth(400)
        self.models_directory_line_edit.setClearButtonEnabled(True)
        self.models_directory_line_edit.textChanged.connect(
            self.show_restart_warning)
        grid_layout.addWidget(self.models_directory_line_edit, 0, 1,
                              Qt.AlignmentFlag.AlignLeft)

        models_directory_button = QPushButton('Select Directory...')
        models_directory_button.setFixedWidth(
            int(models_directory_button.sizeHint().width() * 1.3))
        models_directory_button.clicked.connect(self.set_models_directory_path)
        grid_layout.addWidget(models_directory_button, 1, 1,
                              Qt.AlignmentFlag.AlignLeft)

        # Auto-marking models directory
        grid_layout.addWidget(QLabel('Auto-marking models directory'), 2, 0,
                              Qt.AlignmentFlag.AlignRight)
        self.marking_models_directory_line_edit = SettingsLineEdit(
            key='marking_models_directory_path')
        self.marking_models_directory_line_edit.setMinimumWidth(400)
        self.marking_models_directory_line_edit.setClearButtonEnabled(True)
        grid_layout.addWidget(self.marking_models_directory_line_edit, 2, 1,
                              Qt.AlignmentFlag.AlignLeft)

        marking_models_directory_button = QPushButton('Select Directory...')
        marking_models_directory_button.setFixedWidth(
            int(marking_models_directory_button.sizeHint().width() * 1.3))
        marking_models_directory_button.clicked.connect(
            self.set_marking_models_directory_path)
        grid_layout.addWidget(marking_models_directory_button, 3, 1,
                              Qt.AlignmentFlag.AlignLeft)

        layout.addLayout(grid_layout)
        layout.addStretch()

        scroll_area.setWidget(widget)
        return scroll_area

    def _create_cache_tab(self):
        """Create Cache settings tab."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        grid_layout = QGridLayout()

        # Enable dimension cache
        grid_layout.addWidget(QLabel('Enable dimension cache (.taggui/index.db)'), 0, 0,
                              Qt.AlignmentFlag.AlignRight)
        enable_dimension_cache_check_box = SettingsBigCheckBox(
            key='enable_dimension_cache')
        enable_dimension_cache_check_box.setToolTip(
            'Cache image dimensions in per-folder .taggui/index.db bundles for instant folder reloads')
        grid_layout.addWidget(enable_dimension_cache_check_box, 0, 1,
                              Qt.AlignmentFlag.AlignLeft)

        # Enable thumbnail cache
        grid_layout.addWidget(QLabel('Enable thumbnail cache'), 1, 0,
                              Qt.AlignmentFlag.AlignRight)
        enable_thumbnail_cache_check_box = SettingsBigCheckBox(
            key='enable_thumbnail_cache')
        enable_thumbnail_cache_check_box.setToolTip(
            'Cache generated thumbnails to disk for instant display on reload')
        grid_layout.addWidget(enable_thumbnail_cache_check_box, 1, 1,
                              Qt.AlignmentFlag.AlignLeft)

        # Thumbnail cache location
        grid_layout.addWidget(QLabel('Thumbnail cache location'), 2, 0,
                              Qt.AlignmentFlag.AlignRight)
        self.thumbnail_cache_location_line_edit = SettingsLineEdit(
            key='thumbnail_cache_location')
        self.thumbnail_cache_location_line_edit.setMinimumWidth(400)
        self.thumbnail_cache_location_line_edit.setPlaceholderText(
            'Default: ~/.taggui_cache/thumbnails')
        self.thumbnail_cache_location_line_edit.setToolTip(
            'Leave empty for default location. Change to move cache to custom directory.')
        grid_layout.addWidget(self.thumbnail_cache_location_line_edit, 2, 1,
                              Qt.AlignmentFlag.AlignLeft)

        thumbnail_cache_location_button = QPushButton('Browse...')
        thumbnail_cache_location_button.clicked.connect(
            self.choose_thumbnail_cache_location)
        grid_layout.addWidget(thumbnail_cache_location_button, 3, 1,
                              Qt.AlignmentFlag.AlignLeft)

        # Cache management section (continue grid layout)
        grid_layout.addWidget(QLabel(''), 4, 0)  # Spacer row

        grid_layout.addWidget(QLabel('Cache Management'), 5, 0,
                              Qt.AlignmentFlag.AlignRight)

        cache_buttons_layout = QVBoxLayout()
        cache_buttons_layout.setSpacing(10)

        # Clear current directory cache button
        self.clear_current_button = QPushButton('Clear Current Directory Cache')
        self.clear_current_button.setToolTip(
            'Delete the image index database (.taggui/index.db) and thumbnails for the currently loaded directory only')
        self.clear_current_button.clicked.connect(self.clear_current_directory_cache)

        # Size label and calculate button for current directory
        self.clear_current_size_label = QLabel('(click to calculate)')
        self.clear_current_size_label.setStyleSheet('color: #666; font-size: 10px; margin-left: 10px;')

        self.calc_current_size_button = QPushButton('Calculate')
        self.calc_current_size_button.setToolTip('Calculate cache size for current directory')
        self.calc_current_size_button.clicked.connect(self._calculate_current_directory_size)

        # Current directory row (button + size + calc)
        current_row_layout = QHBoxLayout()
        current_row_layout.setSpacing(10)
        current_row_layout.addWidget(self.clear_current_button)
        current_row_layout.addWidget(self.clear_current_size_label)
        current_row_layout.addWidget(self.calc_current_size_button)
        current_row_layout.addStretch()

        # Clear all cache button
        self.clear_all_button = QPushButton('Clear All Thumbnail Cache')
        self.clear_all_button.setToolTip(
            'Delete all cached thumbnails (will be regenerated on next use)')
        self.clear_all_button.setStyleSheet('QPushButton { color: #d32f2f; }')  # Red text for destructive action
        self.clear_all_button.clicked.connect(self.clear_all_thumbnail_cache)

        # Size label and calculate button for all cache
        self.clear_all_size_label = QLabel('(click to calculate)')
        self.clear_all_size_label.setStyleSheet('color: #666; font-size: 10px; margin-left: 10px;')

        self.calc_all_size_button = QPushButton('Calculate')
        self.calc_all_size_button.setToolTip('Calculate total thumbnail cache size')
        self.calc_all_size_button.clicked.connect(self._calculate_all_cache_size)

        # All cache row (button + size + calc)
        all_row_layout = QHBoxLayout()
        all_row_layout.setSpacing(10)
        all_row_layout.addWidget(self.clear_all_button)
        all_row_layout.addWidget(self.clear_all_size_label)
        all_row_layout.addWidget(self.calc_all_size_button)
        all_row_layout.addStretch()

        # Clear all databases button
        self.clear_all_db_button = QPushButton('Clear All Image Index Databases')
        self.clear_all_db_button.setToolTip(
            'Delete all .taggui/index.db bundles from all previously opened directories. '
            'Use this if databases are corrupted or to free disk space.')
        self.clear_all_db_button.setStyleSheet('QPushButton { color: #d32f2f; }')  # Red text
        self.clear_all_db_button.clicked.connect(self.clear_all_databases)

        # Size label and calculate button for all databases
        self.clear_all_db_size_label = QLabel('(click to calculate)')
        self.clear_all_db_size_label.setStyleSheet('color: #666; font-size: 10px; margin-left: 10px;')

        self.calc_all_db_size_button = QPushButton('Calculate')
        self.calc_all_db_size_button.setToolTip('Calculate total database size')
        self.calc_all_db_size_button.clicked.connect(self._calculate_all_db_size)

        # All databases row (button + size + calc)
        all_db_row_layout = QHBoxLayout()
        all_db_row_layout.setSpacing(10)
        all_db_row_layout.addWidget(self.clear_all_db_button)
        all_db_row_layout.addWidget(self.clear_all_db_size_label)
        all_db_row_layout.addWidget(self.calc_all_db_size_button)
        all_db_row_layout.addStretch()

        # Make all clear buttons the same width (use the wider one)
        max_width = max(self.clear_current_button.sizeHint().width(),
                       self.clear_all_button.sizeHint().width(),
                       self.clear_all_db_button.sizeHint().width())
        button_width = int(max_width * 1.1)
        self.clear_current_button.setFixedWidth(button_width)
        self.clear_all_button.setFixedWidth(button_width)
        self.clear_all_db_button.setFixedWidth(button_width)

        # Make all calculate buttons compact and same width
        calc_button_width = self.calc_current_size_button.sizeHint().width()
        self.calc_current_size_button.setFixedWidth(calc_button_width)
        self.calc_all_size_button.setFixedWidth(calc_button_width)
        self.calc_all_db_size_button.setFixedWidth(calc_button_width)

        cache_buttons_layout.addLayout(current_row_layout)
        cache_buttons_layout.addSpacing(10)
        cache_buttons_layout.addLayout(all_row_layout)
        cache_buttons_layout.addSpacing(10)
        cache_buttons_layout.addLayout(all_db_row_layout)

        grid_layout.addLayout(cache_buttons_layout, 5, 1,
                              Qt.AlignmentFlag.AlignLeft)

        layout.addLayout(grid_layout)
        layout.addStretch()

        scroll_area.setWidget(widget)
        return scroll_area

    def _create_spell_check_tab(self):
        """Create Spell Check settings tab."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        grid_layout = QGridLayout()

        # Enable spell checking
        grid_layout.addWidget(QLabel('Enable spell checking'), 0, 0,
                              Qt.AlignmentFlag.AlignRight)
        self.spell_check_enabled = SettingsBigCheckBox(
            key='spell_check_enabled',
            default=True)
        self.spell_check_enabled.stateChanged.connect(self.show_restart_warning)
        grid_layout.addWidget(self.spell_check_enabled, 0, 1,
                              Qt.AlignmentFlag.AlignLeft)

        # Grammar check mode
        grid_layout.addWidget(QLabel('Grammar check mode'), 1, 0,
                              Qt.AlignmentFlag.AlignRight)
        self.grammar_check_mode_combo = QComboBox()
        self.grammar_check_mode_combo.addItem('Disabled', GrammarCheckMode.DISABLED.value)
        self.grammar_check_mode_combo.addItem('Free API (20 req/min)', GrammarCheckMode.FREE_API.value)
        self.grammar_check_mode_combo.addItem('Local Server (requires Java)', GrammarCheckMode.LOCAL_SERVER.value)

        # Load current grammar check mode
        current_mode = settings.value('grammar_check_mode',
                                     defaultValue=GrammarCheckMode.FREE_API.value,
                                     type=str)
        for i in range(self.grammar_check_mode_combo.count()):
            if self.grammar_check_mode_combo.itemData(i) == current_mode:
                self.grammar_check_mode_combo.setCurrentIndex(i)
                break

        self.grammar_check_mode_combo.currentIndexChanged.connect(
            lambda: self._save_grammar_mode())
        grid_layout.addWidget(self.grammar_check_mode_combo, 1, 1,
                              Qt.AlignmentFlag.AlignLeft)

        layout.addLayout(grid_layout)
        layout.addStretch()

        scroll_area.setWidget(widget)
        return scroll_area

    def _create_advanced_tab(self):
        """Create Advanced settings tab."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        workflow_group, workflow_grid = self._create_settings_group('Workflow')
        display_group, display_grid = self._create_settings_group('Image List Display')
        maintenance_group, maintenance_grid = self._create_settings_group('Folder Maintenance')
        diagnostics_group, diagnostics_grid = self._create_settings_group('Diagnostics')
        video_group, video_grid = self._create_settings_group('Video and GPU')

        # Trainer target resolution
        workflow_grid.addWidget(QLabel('Trainer target resolution (for exact bucket snap)'), 0, 0,
                                Qt.AlignmentFlag.AlignRight)
        trainer_target_resolution_spin_box = SettingsSpinBox(
            key='trainer_target_resolution',
            minimum=256, maximum=4096)
        trainer_target_resolution_spin_box.setToolTip(
            'Set your trainer\'s target resolution (e.g., 1024 for 1024x1024). '
            'Use Shift+Ctrl+drag to snap crops to exact buckets for this resolution.')
        workflow_grid.addWidget(trainer_target_resolution_spin_box, 0, 1,
                                Qt.AlignmentFlag.AlignLeft)

        # Masonry/List auto-switch threshold
        display_grid.addWidget(QLabel('Keep masonry until (thumbnail px)'), 0, 0,
                               Qt.AlignmentFlag.AlignRight)
        masonry_switch_threshold_spin_box = SettingsSpinBox(
            key='masonry_list_switch_threshold',
            minimum=64, maximum=1024, default=150)
        masonry_switch_threshold_spin_box.setToolTip(
            'Auto-switches to List mode when thumbnail size reaches this value.\n'
            'Higher value = masonry allowed for larger thumbnails.\n'
            'Set above 512 to effectively disable auto-switch.\n'
            'Applied live.')
        display_grid.addWidget(masonry_switch_threshold_spin_box, 0, 1,
                               Qt.AlignmentFlag.AlignLeft)

        display_grid.addWidget(QLabel('Image list title strip height (px)'), 1, 0,
                               Qt.AlignmentFlag.AlignRight)
        title_strip_height_spin_box = SettingsSpinBox(
            key='image_list_title_strip_height',
            minimum=4, maximum=32, default=8)
        title_strip_height_spin_box.setToolTip(
            'Controls the compact image-list dock title strip height.\n'
            'Applied live.')
        display_grid.addWidget(title_strip_height_spin_box, 1, 1,
                               Qt.AlignmentFlag.AlignLeft)

        display_grid.addWidget(QLabel('Image list footer strip height (px)'), 2, 0,
                               Qt.AlignmentFlag.AlignRight)
        footer_strip_height_spin_box = SettingsSpinBox(
            key='image_list_footer_strip_height',
            minimum=4, maximum=32, default=8)
        footer_strip_height_spin_box.setToolTip(
            'Controls the compact image-list dock footer strip height.\n'
            'Applied live.')
        display_grid.addWidget(footer_strip_height_spin_box, 2, 1,
                               Qt.AlignmentFlag.AlignLeft)

        display_grid.addWidget(QLabel('Floating masonry wall gap (px)'), 3, 0,
                               Qt.AlignmentFlag.AlignRight)
        floating_wall_gap_spin_box = SettingsSpinBox(
            key='floating_viewer_wall_gap_px',
            minimum=0, maximum=64, default=6)
        floating_wall_gap_spin_box.setToolTip(
            'Controls masonry spacing everywhere:\n'
            '- gap between floating windows\n'
            '- gap to the screen edges\n'
            '- Open in Masonry Wall and Arrange as Masonry Wall\n'
            '0 = no gap.\n'
            'Applied live.'
        )
        display_grid.addWidget(floating_wall_gap_spin_box, 3, 1,
                               Qt.AlignmentFlag.AlignLeft)

        display_grid.addWidget(QLabel('Floating masonry alignment'), 4, 0,
                               Qt.AlignmentFlag.AlignRight)
        floating_wall_alignment_combo = SettingsComboBox(
            key='floating_viewer_wall_alignment',
            default='Top center')
        floating_wall_alignment_combo.addItems(['Top left', 'Top center', 'Top right'])
        floating_wall_alignment_combo.setToolTip(
            'Controls where floating-window masonry layouts are anchored horizontally.\n'
            'top_left leaves continuous free space on the right.\n'
            'top_center matches the previous default behavior.\n'
            'top_right leaves continuous free space on the left.\n'
            'Applied live.'
        )
        display_grid.addWidget(floating_wall_alignment_combo, 4, 1,
                               Qt.AlignmentFlag.AlignLeft)

        display_grid.addWidget(QLabel('Rearrange preserves screen order'), 5, 0,
                               Qt.AlignmentFlag.AlignRight)
        floating_rearrange_preserve_order_check_box = SettingsBigCheckBox(
            key='floating_viewer_rearrange_preserve_screen_order'
        )
        floating_rearrange_preserve_order_check_box.setToolTip(
            'When enabled, Arrange as Masonry Wall keeps the current\n'
            'top-left to bottom-right screen order of your floating windows.\n'
            'When disabled, rearrange uses the neutral pack order instead.\n'
            'Applied live.'
        )
        display_grid.addWidget(floating_rearrange_preserve_order_check_box, 5, 1,
                               Qt.AlignmentFlag.AlignLeft)

        # Floating viewer detail zoom fallback
        display_grid.addWidget(QLabel('Floating double-click detail zoom (%)'), 6, 0,
                               Qt.AlignmentFlag.AlignRight)
        floating_detail_zoom_spin_box = SettingsSpinBox(
            key='floating_double_click_detail_zoom_percent',
            minimum=110, maximum=1600, default=400)
        floating_detail_zoom_spin_box.setToolTip(
            'Fallback zoom amount used in spawned/floating viewers when\n'
            'double-click cannot apply width/height auto-fill and media is not pannable.\n'
            '100 = 1x (no change), 400 = 4x.\n'
            'Applied live (no restart).')
        display_grid.addWidget(floating_detail_zoom_spin_box, 6, 1,
                               Qt.AlignmentFlag.AlignLeft)

        display_grid.addWidget(QLabel('Floating hold opacity (%)'), 7, 0,
                               Qt.AlignmentFlag.AlignRight)
        floating_hold_opacity_slider = SettingsSlider(
            key='floating_viewer_hold_opacity',
            minimum=0,
            maximum=100,
            default=46,
        )
        floating_hold_opacity_slider.setToolTip(
            'Controls how visible spawned/floating viewers remain while hold mode is enabled.\n'
            '0 = fully transparent.\n'
            '100 = fully opaque.\n'
            'Applied live.'
        )
        display_grid.addWidget(floating_hold_opacity_slider, 7, 1,
                               Qt.AlignmentFlag.AlignLeft)

        display_grid.addWidget(QLabel('Floating resize keeps aspect ratio by default'), 8, 0,
                               Qt.AlignmentFlag.AlignRight)
        floating_resize_preserve_aspect_check_box = SettingsBigCheckBox(
            key='floating_resize_preserve_aspect_by_default'
        )
        floating_resize_preserve_aspect_check_box.setToolTip(
            'When enabled, dragging a floating viewer resize edge/corner preserves\n'
            'the current viewer aspect ratio by default, and holding Shift temporarily\n'
            'switches to free resize.\n'
            'When disabled, the current behavior stays the same: free resize by default,\n'
            'hold Shift to preserve aspect ratio.\n'
            'Applied live (no restart).'
        )
        display_grid.addWidget(floating_resize_preserve_aspect_check_box, 8, 1,
                               Qt.AlignmentFlag.AlignLeft)

        workflow_grid.addWidget(QLabel('Image double-click action'), 1, 0,
                                Qt.AlignmentFlag.AlignRight)
        image_list_double_click_combo = SettingsComboBox(
            key='image_list_double_click_action',
            default='spawn viewer')
        image_list_double_click_combo.addItems(['spawn viewer', 'system default app'])
        image_list_double_click_combo.setToolTip(
            'Controls what double-clicking a thumbnail does.\n\n'
            'spawn viewer: open the clicked media in a spawned floating viewer.\n'
            'system default app: open the clicked media with the OS default application.\n\n'
            'Ctrl+double-click always performs the alternate action.\n'
            'Alt+double-click still opens Windows Explorer.\n'
            'Applied live (no restart).'
        )
        workflow_grid.addWidget(image_list_double_click_combo, 1, 1,
                                Qt.AlignmentFlag.AlignLeft)

        maintenance_grid.addWidget(QLabel('Repair extensionless images on folder scan'), 0, 0,
                                   Qt.AlignmentFlag.AlignRight)
        repair_extensionless_images_check_box = SettingsBigCheckBox(
            key='repair_extensionless_images')
        repair_extensionless_images_check_box.setToolTip(
            'Off by default. When enabled, folder scans inspect files with no extension. '
            'If a JPEG, PNG, GIF, WebP, BMP, TIFF, or JPEG XL header is found, TagGUI '
            'renames the file to add the detected extension before adding it to the image list.')
        repair_extensionless_images_check_box.stateChanged.connect(self.show_restart_warning)
        maintenance_grid.addWidget(repair_extensionless_images_check_box, 0, 1,
                                   Qt.AlignmentFlag.AlignLeft)

        maintenance_grid.addWidget(QLabel('Current folder extensionless repair'), 1, 0,
                                   Qt.AlignmentFlag.AlignRight)
        repair_current_folder_btn = QPushButton('Scan Current Folder...')
        repair_current_folder_btn.setToolTip(
            'Manually scan the currently loaded folder for files with no extension. '
            'Detected images are renamed and added to the image list without clearing caches.')
        repair_current_folder_btn.clicked.connect(self.repair_current_folder_extensionless_images)
        maintenance_grid.addWidget(repair_current_folder_btn, 1, 1,
                                   Qt.AlignmentFlag.AlignLeft)

        diagnostics_grid.addWidget(QLabel('Diagnostic log mode'), 0, 0,
                                   Qt.AlignmentFlag.AlignRight)
        diagnostic_log_mode_combo = SettingsComboBox(
            key='diagnostic_log_mode',
            default='essential')
        diagnostic_log_mode_combo.addItems(['off', 'essential', 'verbose'])
        diagnostic_log_mode_combo.setToolTip(
            'Controls runtime diagnostic logging.\n\n'
            'off: suppress debug/runtime diagnostics.\n'
            'essential: keep important navigation/debug lines such as page jumps and selection saves.\n'
            'verbose: emit the full masonry/pagination diagnostic stream.\n\n'
            'Applied live (no restart).'
        )
        diagnostics_grid.addWidget(diagnostic_log_mode_combo, 0, 1,
                                   Qt.AlignmentFlag.AlignLeft)

        self._add_gpu_video_settings(grid_layout=video_grid, start_row=0)

        layout.addWidget(workflow_group)
        layout.addWidget(display_group)
        layout.addWidget(maintenance_group)
        layout.addWidget(diagnostics_group)
        layout.addWidget(video_group)
        layout.addStretch()

        scroll_area.setWidget(widget)
        return scroll_area

    @staticmethod
    def _create_settings_group(title: str) -> tuple[QGroupBox, QGridLayout]:
        group = QGroupBox(title)
        grid = QGridLayout(group)
        grid.setColumnStretch(2, 1)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        return group, grid

    @Slot()
    def repair_current_folder_extensionless_images(self):
        """Manually repair extensionless images in the currently loaded folder."""
        existing_thread = getattr(self, '_extensionless_repair_thread', None)
        if existing_thread is not None and existing_thread.isRunning():
            QMessageBox.information(
                self,
                'Scan Already Running',
                'The current folder extensionless image scan is already running.'
            )
            return

        main_window = self.parent()
        current_dir = None
        if hasattr(main_window, 'directory_path') and main_window.directory_path:
            current_dir = Path(main_window.directory_path)
        elif settings.contains('directory_path'):
            directory_path_str = settings.value('directory_path', type=str)
            if directory_path_str:
                current_dir = Path(directory_path_str)

        if not current_dir or not current_dir.exists():
            QMessageBox.warning(
                self,
                'No Directory Loaded',
                'No directory is currently loaded. Please load a directory first.'
            )
            return

        reply = QMessageBox.question(
            self,
            'Scan Current Folder',
            f'This scans the current folder for files with no extension and renames '
            f'detected images to their real image extension.\n\n'
            f'{current_dir}\n\n'
            f'Existing cache data is not cleared.\n\n'
            f'Continue?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        progress = QProgressDialog(
            'Scanning extensionless files...',
            'Cancel',
            0,
            0,
            self,
        )
        progress.setWindowTitle('Repair Extensionless Images')
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.show()

        repair_thread = ExtensionlessRepairThread(current_dir, self)
        self._extensionless_repair_thread = repair_thread
        self._extensionless_repair_progress = progress
        progress.canceled.connect(repair_thread.cancel)

        def update_progress(file_count: int, extensionless_count: int):
            if progress.wasCanceled():
                return
            progress.setLabelText(
                f'Scanning extensionless files...\n'
                f'Files checked: {int(file_count):,}\n'
                f'Extensionless files found: {int(extensionless_count):,}'
            )

        def cleanup_progress():
            progress.close()
            progress.deleteLater()
            if getattr(self, '_extensionless_repair_thread', None) is repair_thread:
                self._extensionless_repair_thread = None
            if getattr(self, '_extensionless_repair_progress', None) is progress:
                self._extensionless_repair_progress = None

        def show_error(message: str):
            cleanup_progress()
            QMessageBox.critical(
                self,
                'Extensionless Image Scan Failed',
                f'Failed to scan current folder:\n\n{message}'
            )

        def show_result(result: dict):
            cleanup_progress()
            repaired_paths = result.get('repaired_paths') or []
            added_count = 0
            if repaired_paths and hasattr(main_window, 'image_list_model'):
                try:
                    added_count = main_window.image_list_model.add_generated_media_batch(
                        repaired_paths
                    )
                except Exception as e:
                    print(f"[SCAN] Warning: couldn't add repaired images to current model: {e}")

            title = (
                'Extensionless Image Scan Cancelled'
                if result.get('cancelled', False)
                else 'Extensionless Image Scan Complete'
            )
            QMessageBox.information(
                self,
                title,
                f'Files checked: {int(result.get("file_count", 0) or 0):,}\n'
                f'Extensionless files found: {int(result.get("extensionless_count", 0) or 0):,}\n'
                f'Repaired images: {int(result.get("repaired_count", 0) or 0):,}\n'
                f'Added to image list: {int(added_count):,}\n'
                f'Skipped from repair cache: {int(result.get("skipped_cached_count", 0) or 0):,}\n'
                f'New rename failures: {int(result.get("rename_failed_count", 0) or 0):,}'
            )

        repair_thread.progress_changed.connect(update_progress)
        repair_thread.result_ready.connect(show_result)
        repair_thread.error_raised.connect(show_error)
        repair_thread.finished.connect(repair_thread.deleteLater)
        repair_thread.start()

    def _get_cache_size(self, directory: Path) -> str:
        """
        Calculate total cache size in human-readable format.

        Args:
            directory: Directory to calculate size for

        Returns:
            Human-readable size string (e.g., "234 MB")
        """
        if not directory.exists():
            return "0 B"

        try:
            total_size = 0
            for file_path in directory.rglob('*'):
                if file_path.is_file():
                    total_size += file_path.stat().st_size

            # Convert to human-readable format
            for unit in ['B', 'KB', 'MB', 'GB']:
                if total_size < 1024:
                    return f"{total_size:.1f} {unit}" if total_size > 0 else f"{int(total_size)} {unit}"
                total_size /= 1024

            return f"{total_size:.1f} TB"
        except Exception:
            return "? (error)"

    def _add_gpu_video_settings(self, grid_layout: QGridLayout, start_row: int):
        """Add advanced GPU/video backend settings block."""
        row = start_row

        # Playback backend selector (migration scaffold; runtime currently falls back to qt_hybrid)
        grid_layout.addWidget(QLabel('Video playback backend'), row, 0,
                              Qt.AlignmentFlag.AlignRight)
        self.video_playback_backend_combo = SettingsComboBox(
            key='video_playback_backend',
            default=PLAYBACK_BACKEND_QT_HYBRID,
        )
        self.video_playback_backend_combo.addItems(PLAYBACK_BACKEND_CHOICES)
        self.video_playback_backend_combo.setToolTip(
            'Select preferred playback engine.\n\n'
            'qt_hybrid: Current stable backend (Qt + OpenCV hybrid).\n'
            'mpv_experimental: Experimental MPV backend.\n'
            'vlc_experimental: Experimental libVLC backend.\n\n'
            f'mpv availability in current runtime: {"yes" if MPV_BACKEND_AVAILABLE else "no"}.\n'
            f'vlc availability in current runtime: {"yes" if VLC_BACKEND_AVAILABLE else "no"}.\n'
            'When unavailable, selected experimental backend falls back to qt_hybrid.\n'
            + (f'\nmpv load error: {MPV_BACKEND_ERROR}' if (not MPV_BACKEND_AVAILABLE and MPV_BACKEND_ERROR) else '')
            + (f'\nvlc load error: {VLC_BACKEND_ERROR}' if (not VLC_BACKEND_AVAILABLE and VLC_BACKEND_ERROR) else '')
            + (
                f"\n\nSearched runtime dirs:\n- " + "\n- ".join(MPV_RUNTIME_SEARCHED_DIRS[:6])
                if MPV_RUNTIME_SEARCHED_DIRS else
                '\n\nSearched runtime dirs (mpv): none found with mpv runtime files.'
            )
            + (
                f"\n\nSearched runtime dirs (vlc):\n- " + "\n- ".join(VLC_RUNTIME_SEARCHED_DIRS[:6])
                if VLC_RUNTIME_SEARCHED_DIRS else
                '\n\nSearched runtime dirs (vlc): none found with vlc runtime files.'
            )
        )
        self.video_playback_backend_combo.currentTextChanged.connect(
            self._on_playback_backend_changed
        )
        grid_layout.addWidget(self.video_playback_backend_combo, row, 1,
                              Qt.AlignmentFlag.AlignLeft)
        row += 1

        self.mpv_download_btn = QPushButton('Download libmpv-2.dll for Windows ↗')
        self.mpv_download_btn.setToolTip(
            'Opens the official mpv Windows builds page on SourceForge.\n'
            'Download the latest libmpv package, extract libmpv-2.dll,\n'
            'and place it in: third_party/mpv/windows-x86_64/'
        )
        self.mpv_download_btn.clicked.connect(self._open_mpv_download_page)
        self.mpv_download_btn.hide()
        grid_layout.addWidget(self.mpv_download_btn, row, 1,
                              Qt.AlignmentFlag.AlignLeft)
        row += 1

        # Playback GPU preference (OS-level policy for Qt multimedia backend)
        grid_layout.addWidget(QLabel('Playback GPU preference'), row, 0,
                              Qt.AlignmentFlag.AlignRight)
        self.video_playback_gpu_combo = SettingsComboBox(
            key='video_playback_gpu_preference',
            default='system_default')
        self.video_playback_gpu_combo.addItems([
            'system_default',
            'high_performance',
            'power_saving',
        ])
        self.video_playback_gpu_combo.setToolTip(
            'Preferred GPU policy for live playback/rendering (Qt/OS controlled).\n\n'
            'system_default: Let OS/driver decide.\n'
            'high_performance: Prefer discrete/high-power GPU.\n'
            'power_saving: Prefer integrated/low-power GPU.\n\n'
            'Important: On Windows this is applied in OS Graphics Settings per app.\n'
            'Use the button below to open that panel. Restart TagGUI after changing.'
        )
        self.video_playback_gpu_combo.currentTextChanged.connect(
            self._on_playback_gpu_preference_changed
        )
        grid_layout.addWidget(self.video_playback_gpu_combo, row, 1,
                              Qt.AlignmentFlag.AlignLeft)
        row += 1

        self.open_os_graphics_settings_btn = QPushButton('Open OS Graphics Settings...')
        self.open_os_graphics_settings_btn.clicked.connect(self._open_os_graphics_settings)
        self.open_os_graphics_settings_btn.setToolTip(
            'Open Windows Graphics Settings (Advanced graphics) where you can force\n'
            'TagGUI to use Power saving or High performance GPU.'
        )
        if not sys.platform.startswith('win'):
            self.open_os_graphics_settings_btn.setEnabled(False)
            self.open_os_graphics_settings_btn.setToolTip(
                'OS graphics settings shortcut is currently available on Windows only.'
            )
        grid_layout.addWidget(self.open_os_graphics_settings_btn, row, 1,
                              Qt.AlignmentFlag.AlignLeft)
        row += 1

        # FFmpeg acceleration mode (used by encoding/processing tools)
        grid_layout.addWidget(QLabel('FFmpeg acceleration mode'), row, 0,
                              Qt.AlignmentFlag.AlignRight)
        self.video_ffmpeg_accel_mode_combo = SettingsComboBox(
            key='video_ffmpeg_accel_mode',
            default='none')
        self.video_ffmpeg_accel_mode_combo.addItems(['none', 'cuda'])
        self.video_ffmpeg_accel_mode_combo.setToolTip(
            'Acceleration mode for FFmpeg-based processing operations\n'
            '(crop/extract/fix/validation), not live playback.\n\n'
            'none: CPU/default decode.\n'
            'cuda: NVIDIA CUDA decode acceleration.'
        )
        self.video_ffmpeg_accel_mode_combo.currentTextChanged.connect(
            self._on_ffmpeg_accel_mode_changed
        )
        grid_layout.addWidget(self.video_ffmpeg_accel_mode_combo, row, 1,
                              Qt.AlignmentFlag.AlignLeft)
        row += 1

        grid_layout.addWidget(QLabel('FFmpeg CUDA device index'), row, 0,
                              Qt.AlignmentFlag.AlignRight)
        self.video_ffmpeg_cuda_device_spin = SettingsSpinBox(
            key='video_ffmpeg_cuda_device',
            minimum=0,
            maximum=15,
            default=0)
        self.video_ffmpeg_cuda_device_spin.setToolTip(
            'NVIDIA GPU index used by FFmpeg when acceleration mode is "cuda".\n'
            'Examples:\n'
            '- 0: first NVIDIA GPU\n'
            '- 1: second NVIDIA GPU\n\n'
            'If unsure, start with 0.'
        )
        self.video_ffmpeg_cuda_device_spin.setEnabled(
            self.video_ffmpeg_accel_mode_combo.currentText() == 'cuda'
        )
        grid_layout.addWidget(self.video_ffmpeg_cuda_device_spin, row, 1,
                              Qt.AlignmentFlag.AlignLeft)
        row += 1

        grid_layout.addWidget(QLabel('Detected GPUs'), row, 0,
                              Qt.AlignmentFlag.AlignRight)
        gpu_detect_row = QHBoxLayout()
        self.detected_gpus_label = QLabel('')
        self.detected_gpus_label.setWordWrap(True)
        self.detected_gpus_label.setMinimumWidth(360)
        refresh_gpu_btn = QPushButton('Refresh')
        refresh_gpu_btn.clicked.connect(self._refresh_detected_gpus)
        gpu_detect_row.addWidget(self.detected_gpus_label)
        gpu_detect_row.addWidget(refresh_gpu_btn)
        gpu_detect_row.addStretch()
        grid_layout.addLayout(gpu_detect_row, row, 1, Qt.AlignmentFlag.AlignLeft)
        self._refresh_detected_gpus()

    @Slot()
    def _calculate_current_directory_size(self):
        """Calculate cache size for current directory."""
        self.clear_current_size_label.setText('Calculating...')
        self.calc_current_size_button.setEnabled(False)

        from PySide6.QtCore import QTimer

        def do_calculation():
            thumbnail_cache = get_thumbnail_cache()
            current_dir = None
            if settings.contains('directory_path'):
                directory_path_str = settings.value('directory_path', type=str)
                if directory_path_str:
                    current_dir = Path(directory_path_str)

            if not current_dir or not current_dir.exists():
                self.clear_current_size_label.setText('(no directory loaded)')
                self.calc_current_size_button.setEnabled(True)
                return

            try:
                dir_cache_size = ImageIndexDB.total_database_bundle_size(
                    current_dir, include_legacy=True)

                if thumbnail_cache.enabled and thumbnail_cache.cache_dir.exists():
                    from models.image_list_model import get_file_paths
                    image_suffixes_string = settings.value(
                        'image_list_file_formats',
                        defaultValue=DEFAULT_SETTINGS['image_list_file_formats'], type=str)
                    image_suffixes = parse_image_list_formats(image_suffixes_string)

                    file_paths = get_file_paths(current_dir)
                    image_paths = [path for path in file_paths if path.suffix.lower() in image_suffixes]

                    for image_path in image_paths:
                        try:
                            mtime = image_path.stat().st_mtime
                            cache_key = thumbnail_cache._get_cache_key(image_path, mtime, 512)
                            cache_path = thumbnail_cache._get_cache_path(cache_key)
                            if cache_path.exists():
                                dir_cache_size += cache_path.stat().st_size
                        except Exception:
                            pass

                if dir_cache_size > 0:
                    self.clear_current_size_label.setText(self._format_size(dir_cache_size))
                else:
                    self.clear_current_size_label.setText('(empty)')
            except Exception:
                self.clear_current_size_label.setText('(error)')
            finally:
                self.calc_current_size_button.setEnabled(True)

        # Run calculation after event loop returns to prevent blocking dialog open
        QTimer.singleShot(10, do_calculation)

    @Slot()
    def _calculate_all_cache_size(self):
        """Calculate total thumbnail cache size."""
        self.clear_all_size_label.setText('Calculating...')
        self.calc_all_size_button.setEnabled(False)

        from PySide6.QtCore import QTimer

        def do_calculation():
            thumbnail_cache = get_thumbnail_cache()

            if not thumbnail_cache.enabled or not thumbnail_cache.cache_dir.exists():
                self.clear_all_size_label.setText('(empty)')
                self.calc_all_size_button.setEnabled(True)
                return

            try:
                cache_size = self._get_cache_size(thumbnail_cache.cache_dir)
                self.clear_all_size_label.setText(cache_size)
            except Exception:
                self.clear_all_size_label.setText('(error)')
            finally:
                self.calc_all_size_button.setEnabled(True)

        QTimer.singleShot(10, do_calculation)

    @Slot()
    def _calculate_all_db_size(self):
        """Calculate total database size."""
        self.clear_all_db_size_label.setText('Calculating...')
        self.calc_all_db_size_button.setEnabled(False)

        from PySide6.QtCore import QTimer

        def do_calculation():
            try:
                recent_dirs = settings.value('recent_directories', [], type=list)
                total_db_size = 0
                bundle_count = 0

                for dir_path_str in recent_dirs:
                    dir_path = Path(dir_path_str)
                    bundle_size = ImageIndexDB.total_database_bundle_size(
                        dir_path, include_legacy=True)
                    if bundle_size > 0:
                        total_db_size += bundle_size
                        bundle_count += 1

                if bundle_count > 0:
                    size_str = self._format_size(total_db_size)
                    self.clear_all_db_size_label.setText(f"{size_str} ({bundle_count} bundles)")
                else:
                    self.clear_all_db_size_label.setText('(no databases found)')
            except Exception:
                self.clear_all_db_size_label.setText('(error)')
            finally:
                self.calc_all_db_size_button.setEnabled(True)

        QTimer.singleShot(10, do_calculation)

    def _format_size(self, size: int) -> str:
        """Format byte size to human-readable string."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}" if size > 0 else f"{int(size)} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    @Slot()
    def show_restart_warning(self):
        self.warning_label.setText(self.restart_warning)
        self.warning_label.show()

    @Slot(str)
    def _on_skin_changed(self, skin_name: str):
        """Handle video player skin change - applies immediately."""
        # Get main window and apply skin to video controls
        main_window = self.parent()
        if hasattr(main_window, 'video_controls'):
            video_controls = main_window.video_controls
            if hasattr(video_controls, 'switch_skin'):
                success = video_controls.switch_skin(skin_name)
                if success:
                    # Show success message in warning label temporarily
                    self.warning_label.setText(f'✓ Skin "{skin_name}" applied (no restart needed)')
                    self.warning_label.setStyleSheet('color: green;')
                    self.warning_label.show()
                    # Reset after 3 seconds
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(3000, self._reset_warning_label)
                else:
                    self.warning_label.setText(f'Failed to load skin: {skin_name}')
                    self.warning_label.setStyleSheet('color: red;')
                    self.warning_label.show()

    def _reset_warning_label(self):
        """Reset warning label to default state."""
        self.warning_label.hide()
        self.warning_label.setStyleSheet('color: red;')

    @Slot(str)
    def _on_playback_backend_changed(self, backend_name: str):
        configured = normalize_playback_backend_name(backend_name)
        runtime_backend = resolve_runtime_playback_backend(configured)
        show_mpv_download = (
            configured == 'mpv_experimental'
            and not MPV_BACKEND_AVAILABLE
            and sys.platform.startswith('win')
        )
        self.mpv_download_btn.setVisible(show_mpv_download)
        if configured != runtime_backend:
            extra = ''
            if configured == 'mpv_experimental' and MPV_BACKEND_ERROR:
                extra = f' ({MPV_BACKEND_ERROR})'
                if not MPV_RUNTIME_SEARCHED_DIRS and sys.platform.startswith('win'):
                    extra += " Place libmpv-2.dll in 'third_party/mpv/windows-x86_64/'."
            elif configured == 'vlc_experimental' and VLC_BACKEND_ERROR:
                extra = f' ({VLC_BACKEND_ERROR})'
                if not VLC_RUNTIME_SEARCHED_DIRS and sys.platform.startswith('win'):
                    extra += " Place libvlc.dll/libvlccore.dll in 'third_party/vlc/windows-x86_64/'."
            self.warning_label.setText(
                f'Playback backend "{configured}" is not active yet; runtime uses "{runtime_backend}"{extra}.'
            )
            self.warning_label.setStyleSheet('color: #d48806;')
        else:
            self.warning_label.setText(f'Playback backend set to "{runtime_backend}".')
            self.warning_label.setStyleSheet('color: #0a7f2e;')
        self.warning_label.show()

    @Slot(str)
    def _on_playback_gpu_preference_changed(self, _value: str):
        self.warning_label.setText(
            'Playback GPU preference updated. On Windows, confirm this app in OS Graphics Settings, then restart TagGUI.'
        )
        self.warning_label.setStyleSheet('color: #d48806;')
        self.warning_label.show()

    @Slot(str)
    def _on_ffmpeg_accel_mode_changed(self, mode: str):
        self.video_ffmpeg_cuda_device_spin.setEnabled(mode == 'cuda')
        self.warning_label.setText('FFmpeg acceleration preference saved (applies to new processing commands).')
        self.warning_label.setStyleSheet('color: #0a7f2e;')
        self.warning_label.show()

    @Slot()
    def _open_mpv_download_page(self):
        QDesktopServices.openUrl(QUrl(
            'https://sourceforge.net/projects/mpv-player-windows/files/libmpv/'
        ))

    @Slot()
    def _open_os_graphics_settings(self):
        if not sys.platform.startswith('win'):
            QMessageBox.information(
                self,
                'Unsupported Platform',
                'OS graphics settings shortcut is currently available on Windows only.'
            )
            return
        opened = QDesktopServices.openUrl(QUrl('ms-settings:display-advancedgraphics'))
        if not opened:
            QMessageBox.warning(
                self,
                'Could Not Open Settings',
                'Failed to open Windows Graphics Settings automatically.\n'
                'Open Settings > System > Display > Graphics manually.'
            )

    @Slot()
    def _refresh_detected_gpus(self):
        gpus = self._detect_gpu_names()
        if not gpus:
            self.detected_gpus_label.setText('No GPUs detected via system tools.')
            return
        self.detected_gpus_label.setText('; '.join(gpus))

    def _detect_gpu_names(self) -> list[str]:
        names: list[str] = []

        # First try NVIDIA list with stable index order.
        try:
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=index,name', '--format=csv,noheader'],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if line:
                        names.append(f'NVIDIA {line}')
        except Exception:
            pass

        # Fallback to Windows generic adapter list.
        if sys.platform.startswith('win'):
            try:
                result = subprocess.run(
                    ['wmic', 'path', 'win32_VideoController', 'get', 'name'],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                if result.returncode == 0:
                    for line in result.stdout.splitlines():
                        line = line.strip()
                        if line and line.lower() != 'name':
                            if line not in names:
                                names.append(line)
            except Exception:
                pass

        return names

    def disable_insert_space_after_tag_separator_check_box(self):
        self.insert_space_after_tag_separator_check_box.setEnabled(False)
        self.insert_space_after_tag_separator_check_box.setChecked(False)

    @Slot(str)
    def handle_tag_separator_change(self, tag_separator: str):
        if not tag_separator:
            self.warning_label.setText('The tag separator cannot be empty.')
            self.warning_label.show()
            return
        if tag_separator == r'\n':
            tag_separator = '\n'
            self.disable_insert_space_after_tag_separator_check_box()
        else:
            self.insert_space_after_tag_separator_check_box.setEnabled(True)
        settings.setValue('tag_separator', tag_separator)
        self.show_restart_warning()

    @Slot()
    def choose_thumbnail_cache_location(self):
        """Browse for thumbnail cache directory."""
        current_location = settings.value(
            'thumbnail_cache_location',
            defaultValue=DEFAULT_SETTINGS['thumbnail_cache_location'], type=str)

        if not current_location:
            # Use default location as starting point
            from pathlib import Path
            current_location = str(Path.home() / '.taggui_cache' / 'thumbnails')

        directory = QFileDialog.getExistingDirectory(
            self, 'Select Thumbnail Cache Location', current_location)

        if directory:
            self.thumbnail_cache_location_line_edit.setText(directory)
            settings.setValue('thumbnail_cache_location', directory)

    @Slot()
    def set_models_directory_path(self):
        models_directory_path = settings.value(
            'models_directory_path',
            defaultValue=DEFAULT_SETTINGS['models_directory_path'], type=str)
        if models_directory_path:
            initial_directory_path = models_directory_path
        elif settings.contains('directory_path'):
            initial_directory_path = settings.value('directory_path', type=str)
        else:
            initial_directory_path = ''
        models_directory_path = QFileDialog.getExistingDirectory(
            parent=self, caption='Select directory containing auto-captioning '
                                 'models',
            dir=initial_directory_path)
        if models_directory_path:
            self.models_directory_line_edit.setText(models_directory_path)

    @Slot()
    def set_marking_models_directory_path(self):
        marking_models_directory_path = settings.value(
            'marking_models_directory_path',
            defaultValue=DEFAULT_SETTINGS['marking_models_directory_path'], type=str)
        if marking_models_directory_path:
            initial_directory_path = marking_models_directory_path
        elif settings.contains('directory_path'):
            initial_directory_path = settings.value('directory_path', type=str)
        else:
            initial_directory_path = ''
        marking_models_directory_path = QFileDialog.getExistingDirectory(
            parent=self, caption='Select directory containing auto-marking '
                                 'models (YOLO models)',
            dir=initial_directory_path)
        if marking_models_directory_path:
            self.marking_models_directory_line_edit.setText(marking_models_directory_path)

    @Slot()
    def _save_grammar_mode(self):
        """Save the selected grammar check mode to settings."""
        mode_value = self.grammar_check_mode_combo.currentData()
        settings.setValue('grammar_check_mode', mode_value)
        self.show_restart_warning()

    @Slot()
    def clear_current_directory_cache(self):
        """Clear cache for currently loaded directory only."""
        # Get current directory from settings
        current_dir = None
        if settings.contains('directory_path'):
            directory_path_str = settings.value('directory_path', type=str)
            if directory_path_str:
                current_dir = Path(directory_path_str)

        if not current_dir or not current_dir.exists():
            QMessageBox.warning(
                self,
                'No Directory Loaded',
                'No directory is currently loaded. Please load a directory first.'
            )
            return

        # Confirmation dialog
        reply = QMessageBox.question(
            self,
            'Confirm Clear Current Directory Cache',
            f'This will delete:\n\n'
            f'• Image index database (.taggui/index.db)\n'
            f'• All thumbnails for images in:\n'
            f'  {current_dir}\n\n'
            f'Cache will be rebuilt when you reload this directory.\n\n'
            f'Continue?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            deleted_count = 0

            # Close database connection before deleting (avoid WinError 32)
            try:
                main_window = self.parent()
                if hasattr(main_window, 'image_list_model'):
                    image_list_model = main_window.image_list_model
                    if hasattr(image_list_model, '_db') and image_list_model._db:
                        image_list_model._db.close()
                        image_list_model._db = None
                        print("[CACHE] Closed database connection before deletion")
            except Exception as e:
                print(f"[CACHE] Warning: couldn't close DB connection: {e}")

            # Delete image index database bundle (new location + legacy fallback)
            deleted_count += len(ImageIndexDB.delete_database_bundle(
                current_dir, include_legacy=True))

            # Delete thumbnails for this directory
            # We need to delete cached thumbnails that match files in this directory
            thumbnail_cache = get_thumbnail_cache()
            if thumbnail_cache.enabled and thumbnail_cache.cache_dir.exists():
                # Get all image files in current directory
                from models.image_list_model import get_file_paths
                image_suffixes_string = settings.value(
                    'image_list_file_formats',
                    defaultValue=DEFAULT_SETTINGS['image_list_file_formats'], type=str)
                image_suffixes = parse_image_list_formats(image_suffixes_string)

                file_paths = get_file_paths(current_dir)
                image_paths = [path for path in file_paths if path.suffix.lower() in image_suffixes]

                # Delete cache for each image
                for image_path in image_paths:
                    try:
                        mtime = image_path.stat().st_mtime
                        cache_key = thumbnail_cache._get_cache_key(
                            image_path, mtime, 512  # Default thumbnail size
                        )
                        cache_path = thumbnail_cache._get_cache_path(cache_key)
                        if cache_path.exists():
                            cache_path.unlink()
                            deleted_count += 1
                    except Exception:
                        pass  # Skip files that fail

            QMessageBox.information(
                self,
                'Cache Cleared',
                f'Successfully cleared cache for current directory.\n'
                f'Deleted {deleted_count} cache files.\n\n'
                f'Reloading directory...'
            )

            # Reset size label
            self.clear_current_size_label.setText('(cleared - click to recalculate)')

            # Reload directory to rebuild cache
            try:
                main_window = self.parent()
                if hasattr(main_window, 'image_list_model'):
                    # Close dialog first so user sees the reload happening
                    self.accept()
                    main_window.image_list_model.load_directory(current_dir)
            except Exception as e:
                print(f"[CACHE] Warning: couldn't reload directory: {e}")

        except Exception as e:
            QMessageBox.critical(
                self,
                'Error',
                f'Failed to clear cache: {str(e)}'
            )

    @Slot()
    def clear_all_thumbnail_cache(self):
        """Clear all thumbnail cache."""
        thumbnail_cache = get_thumbnail_cache()

        if not thumbnail_cache.enabled:
            QMessageBox.information(
                self,
                'Cache Disabled',
                'Thumbnail cache is currently disabled in settings.'
            )
            return

        if not thumbnail_cache.cache_dir.exists():
            QMessageBox.information(
                self,
                'Cache Empty',
                'Thumbnail cache directory does not exist or is already empty.'
            )
            return

        # Confirmation dialog
        reply = QMessageBox.question(
            self,
            'Confirm Clear All Thumbnail Cache',
            f'This will permanently delete ALL cached thumbnails from:\n'
            f'{thumbnail_cache.cache_dir}\n\n'
            f'Thumbnails will be regenerated when needed.\n\n'
            f'Continue?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            deleted_count = 0

            # Delete all cache files
            for cache_file in thumbnail_cache.cache_dir.rglob('*.webp'):
                try:
                    cache_file.unlink()
                    deleted_count += 1
                except Exception:
                    pass

            # Also delete old PNG files if any remain
            for cache_file in thumbnail_cache.cache_dir.rglob('*.png'):
                try:
                    cache_file.unlink()
                    deleted_count += 1
                except Exception:
                    pass

            QMessageBox.information(
                self,
                'Cache Cleared',
                f'Successfully cleared all thumbnail cache.\n'
                f'Deleted {deleted_count} cached thumbnails.'
            )
            # Reset size label instead of recalculating
            self.clear_all_size_label.setText('(cleared - click to recalculate)')

        except Exception as e:
            QMessageBox.critical(
                self,
                'Error',
                f'Failed to clear cache: {str(e)}'
            )

    @Slot()
    def clear_all_databases(self):
        """Clear all image index database bundles from all recent directories."""
        # Get list of recent directories
        recent_dirs = settings.value('recent_directories', [], type=list)

        if not recent_dirs:
            QMessageBox.information(
                self,
                'No Databases Found',
                'No image index databases found in recent directories.'
            )
            return

        # Find all directories that have a database bundle
        db_dirs = []
        for dir_path_str in recent_dirs:
            dir_path = Path(dir_path_str)
            bundle_paths = [
                path for path in ImageIndexDB.all_bundle_paths(dir_path, include_legacy=True)
                if path.exists()
            ]
            if bundle_paths:
                db_dirs.append((dir_path, bundle_paths))

        if not db_dirs:
            QMessageBox.information(
                self,
                'No Databases Found',
                'No image index databases found in recent directories.'
            )
            return

        # Confirmation dialog
        reply = QMessageBox.question(
            self,
            'Confirm Clear All Image Index Databases',
            f'This will permanently delete {len(db_dirs)} database bundle(s):\n\n'
            f'{chr(10).join([f"• {dir_path.name}/.taggui/index.db" for dir_path, _ in db_dirs[:5]])}'
            f'{f"{chr(10)}...and {len(db_dirs) - 5} more" if len(db_dirs) > 5 else ""}\n\n'
            f'Databases will be rebuilt when you open these directories.\n\n'
            f'Continue?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            deleted_files = 0
            deleted_bundles = 0
            failed_count = 0
            current_loaded_dir = None
            db_dir_set = {dir_path for dir_path, _ in db_dirs}
            current_db_in_use = False

            try:
                main_window = self.parent()
                if hasattr(main_window, 'directory_path') and main_window.directory_path:
                    current_loaded_dir = Path(main_window.directory_path)
                if hasattr(main_window, 'image_list_model'):
                    image_list_model = main_window.image_list_model
                    if (
                        current_loaded_dir is not None
                        and current_loaded_dir in db_dir_set
                        and hasattr(image_list_model, '_db')
                        and image_list_model._db
                    ):
                        current_db_in_use = True
            except Exception:
                pass

            for dir_path, bundle_paths in db_dirs:
                if current_db_in_use and current_loaded_dir is not None and dir_path == current_loaded_dir:
                    failed_count += 1
                    continue
                removed = ImageIndexDB.delete_database_bundle(
                    dir_path, include_legacy=True)
                if removed:
                    deleted_bundles += 1
                    deleted_files += len(removed)
                remaining = [path for path in bundle_paths if path.exists()]
                if remaining:
                    failed_count += 1

            message = (
                f'Successfully deleted {deleted_bundles} database bundle(s) '
                f'({deleted_files} file(s)).'
            )
            if failed_count > 0:
                message += f'\n{failed_count} bundle(s) could not be fully deleted (may be in use).'

            QMessageBox.information(
                self,
                'Databases Cleared',
                message
            )
            # Reset size label instead of recalculating
            self.clear_all_db_size_label.setText('(cleared - click to recalculate)')

        except Exception as e:
            QMessageBox.critical(
                self,
                'Error',
                f'Failed to clear databases: {str(e)}'
            )
