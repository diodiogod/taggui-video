"""Real browser destruction must not delete the application's shared style."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton, QStyle, QStyleOptionSlider
from shiboken6 import isValid

from models.image_list_model import ImageListModel
from models.proxy_image_list_model import ProxyImageListModel
from widgets.image_list import ImageList
from qt_test_helpers import APP, dispose_widget


def test_browser_styles_have_independent_bases_and_preserve_sibling_widgets():
    shared = APP.style()
    original_parent, original_proxy = shared.parent(), shared.proxy()
    model = ImageListModel(96, ',')
    proxy = ProxyImageListModel(model, object(), ',')
    browsers = []
    sibling = QPushButton('Still alive')
    try:
        browsers.extend(ImageList(proxy, ',', 96) for _ in range(2))
        for browser in browsers:
            scrollbar = browser.list_view.verticalScrollBar()
            track = scrollbar.style()
            assert shared.parent() is original_parent
            assert shared.proxy() is original_proxy
            assert track.baseStyle() is not shared
            assert track.baseStyle().parent() is track
            assert track.baseStyle().name() == shared.name()

            scrollbar.resize(20, 250)
            option = QStyleOptionSlider()
            option.initFrom(scrollbar)
            option.orientation = Qt.Vertical
            option.minimum, option.maximum = 0, 100
            option.pageStep, option.singleStep = 10, 1
            option.sliderPosition, option.sliderValue = 55, 55
            option.subControls = QStyle.SubControl.SC_All
            control = QStyle.ComplexControl.CC_ScrollBar
            slider = QStyle.SubControl.SC_ScrollBarSlider
            expected = shared.subControlRect(control, option, slider, scrollbar)
            assert track.subControlRect(control, option, slider, scrollbar) == expected
            assert track.hitTestComplexControl(control, option, expected.center(), scrollbar) == slider

        assert browsers[0].list_view.verticalScrollBar().style().baseStyle() is not (
            browsers[1].list_view.verticalScrollBar().style().baseStyle())
        first = browsers.pop(0)
        first.list_view._masonry_executor.shutdown(wait=True, cancel_futures=True)
        first.list_view._masonry_executor = None
        dispose_widget(first)
        APP.processEvents()
        assert not isValid(first)
        assert isValid(shared)
        assert APP.style() is shared
        assert not sibling.grab().isNull()
        assert not browsers[0].grab().isNull()
    finally:
        for browser in browsers:
            browser.list_view._masonry_executor.shutdown(wait=True, cancel_futures=True)
            browser.list_view._masonry_executor = None
            dispose_widget(browser)
        model.shutdown_background_workers()
        dispose_widget(sibling)
        APP.processEvents()
