from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem

from utils.settings import DEFAULT_SETTINGS, settings


class IdeogramLabelItem(QGraphicsItem):
    _FONT_WEIGHTS = {
        'Normal': QFont.Weight.Normal,
        'Medium': QFont.Weight.Medium,
        'Bold': QFont.Weight.Bold,
        'Black': QFont.Weight.Black,
    }

    def __init__(self, text: str, accent: QColor, parent=None):
        super().__init__(parent)
        self._text = str(text or '')
        self._accent = QColor(accent)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self._bounding_rect = QRectF()
        self._recalculate_geometry()

    def boundingRect(self) -> QRectF:
        return self._bounding_rect

    def paint(self, painter: QPainter, option, widget=None):
        del option, widget
        style = self._style()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        border_pen = QPen(self._accent, style['border_width'])
        border_pen.setCosmetic(True)
        painter.setPen(border_pen)
        painter.setBrush(style['background_color'])
        painter.drawRect(self._bounding_rect)

        outline_margin = style['outline_width'] * 0.5
        baseline_y = outline_margin + style['padding_y'] + style['metrics'].ascent()
        text_path = QPainterPath()
        text_path.addText(
            float(outline_margin + style['padding_x']),
            float(baseline_y),
            style['font'],
            self._text,
        )
        if style['outline_width'] > 0.0:
            outline_pen = QPen(
                style['outline_color'],
                style['outline_width'],
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
            outline_pen.setCosmetic(True)
            painter.strokePath(text_path, outline_pen)
        painter.fillPath(text_path, style['text_color'])

    def refresh_from_settings(self):
        self.prepareGeometryChange()
        self._recalculate_geometry()
        self.update()

    def _style(self) -> dict:
        font_weight_name = str(
            settings.value(
                'ideogram_overlay_font_weight',
                defaultValue=DEFAULT_SETTINGS['ideogram_overlay_font_weight'],
                type=str,
            )
            or DEFAULT_SETTINGS['ideogram_overlay_font_weight']
        )
        font = QFont(
            'DejaVu Sans',
            max(
                6,
                int(
                    settings.value(
                        'ideogram_overlay_font_size',
                        defaultValue=DEFAULT_SETTINGS['ideogram_overlay_font_size'],
                        type=int,
                    )
                ),
            ),
            self._FONT_WEIGHTS.get(font_weight_name, QFont.Weight.Black),
        )
        metrics = QFontMetricsF(font)
        padding_x = max(
            1,
            int(
                settings.value(
                    'ideogram_overlay_chip_padding_x',
                    defaultValue=DEFAULT_SETTINGS['ideogram_overlay_chip_padding_x'],
                    type=int,
                )
            ),
        )
        padding_y = max(
            1,
            int(
                settings.value(
                    'ideogram_overlay_chip_padding_y',
                    defaultValue=DEFAULT_SETTINGS['ideogram_overlay_chip_padding_y'],
                    type=int,
                )
            ),
        )
        background_color = QColor(
            str(
                settings.value(
                    'ideogram_overlay_background_color',
                    defaultValue=DEFAULT_SETTINGS['ideogram_overlay_background_color'],
                    type=str,
                )
                or DEFAULT_SETTINGS['ideogram_overlay_background_color']
            )
        )
        background_color.setAlpha(
            max(
                0,
                min(
                    255,
                    int(
                        settings.value(
                            'ideogram_overlay_background_alpha',
                            defaultValue=DEFAULT_SETTINGS['ideogram_overlay_background_alpha'],
                            type=int,
                        )
                    ),
                ),
            )
        )
        return {
            'font': font,
            'metrics': metrics,
            'padding_x': padding_x,
            'padding_y': padding_y,
            'border_width': max(
                1.0,
                float(
                    settings.value(
                        'ideogram_overlay_border_px',
                        defaultValue=DEFAULT_SETTINGS['ideogram_overlay_border_px'],
                        type=int,
                    )
                ),
            ),
            'outline_width': max(
                0.0,
                float(
                    settings.value(
                        'ideogram_overlay_text_outline_px',
                        defaultValue=DEFAULT_SETTINGS['ideogram_overlay_text_outline_px'],
                        type=int,
                    )
                ),
            ),
            'background_color': background_color,
            'text_color': QColor(
                str(
                    settings.value(
                        'ideogram_overlay_text_color',
                        defaultValue=DEFAULT_SETTINGS['ideogram_overlay_text_color'],
                        type=str,
                    )
                    or DEFAULT_SETTINGS['ideogram_overlay_text_color']
                )
            ),
            'outline_color': QColor(
                str(
                    settings.value(
                        'ideogram_overlay_outline_color',
                        defaultValue=DEFAULT_SETTINGS['ideogram_overlay_outline_color'],
                        type=str,
                    )
                    or DEFAULT_SETTINGS['ideogram_overlay_outline_color']
                )
            ),
        }

    def _recalculate_geometry(self):
        style = self._style()
        text_rect = style['metrics'].boundingRect(self._text)
        outline_margin = style['outline_width'] * 0.5
        self._bounding_rect = QRectF(
            0.0,
            0.0,
            float(text_rect.width() + (style['padding_x'] * 2) + (outline_margin * 2)),
            float(text_rect.height() + (style['padding_y'] * 2) + (outline_margin * 2)),
        )
