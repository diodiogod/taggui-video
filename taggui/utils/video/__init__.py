"""Video editing utilities."""

from importlib import import_module

__all__ = ['FrameEditor', 'SARFixer', 'BatchProcessor', 'VideoEditor', 'VideoValidator']

_LAZY_EXPORTS = {
    'FrameEditor': ('.frame_editor', 'FrameEditor'),
    'SARFixer': ('.sar_fixer', 'SARFixer'),
    'BatchProcessor': ('.batch_processor', 'BatchProcessor'),
    'VideoEditor': ('.video_editor', 'VideoEditor'),
    'VideoValidator': ('.validator', 'VideoValidator'),
}


def __getattr__(name: str):
    """Resolve video helpers independently instead of importing the full suite."""
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
    module_name, attribute_name = target
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value
