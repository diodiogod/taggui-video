"""Bake exclude-marking effects into still-image files."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageFilter
from PySide6.QtCore import QRect


MARKING_EFFECTS = (
    'inpaint — AI (MI-GAN)',
    'inpaint — basic (OpenCV)',
    'blur',
    'blur + noise',
    'grey',
    'grey + noise',
    'black',
    'white',
)


def apply_exclude_effect(
    image_path: Path,
    rectangles: list[QRect],
    effect: str,
    *,
    model_path: Path | None = None,
) -> tuple[bool, str]:
    """Apply an effect inside the supplied rectangles and overwrite the image."""
    effect = str(effect).strip().lower()
    effect = {
        'inpaint (fast)': 'inpaint — basic (opencv)',
    }.get(effect, effect)
    supported_effects = {item.lower() for item in MARKING_EFFECTS}
    if effect not in supported_effects:
        return False, f'Unsupported marking effect: {effect}'
    if not rectangles:
        return False, f'No exclude markings on {image_path.name}'

    try:
        with Image.open(image_path) as source:
            source.load()
            original_format = source.format
            original_info = dict(source.info)
            working = source.convert('RGBA' if source.mode in {'RGBA', 'LA', 'PA'} else 'RGB')

        bounds = QRect(0, 0, working.width, working.height)
        valid_rectangles = []
        for rectangle in rectangles:
            clipped = QRect(rectangle).normalized().intersected(bounds)
            if not clipped.isEmpty() and clipped.isValid():
                valid_rectangles.append(clipped)
        if not valid_rectangles:
            return False, f'No valid exclude markings on {image_path.name}'

        if effect == 'inpaint — ai (mi-gan)':
            if model_path is None or not Path(model_path).is_file():
                return False, 'The MI-GAN model is not available.'
            from utils.migan_inpainter import inpaint_with_migan

            working = inpaint_with_migan(
                working,
                valid_rectangles,
                Path(model_path),
            )
            applied = len(valid_rectangles)
        elif effect == 'inpaint — basic (opencv)':
            try:
                import cv2
                import numpy as np
            except ImportError:
                return False, 'Fast inpainting requires OpenCV and NumPy.'
            rgb = np.asarray(working.convert('RGB'))
            mask = np.zeros((working.height, working.width), dtype=np.uint8)
            for clipped in valid_rectangles:
                mask[
                    clipped.y():clipped.y() + clipped.height(),
                    clipped.x():clipped.x() + clipped.width(),
                ] = 255
            mask = cv2.dilate(mask, np.ones((5, 5), np.uint8), iterations=1)
            inpainted = cv2.inpaint(rgb, mask, 3, cv2.INPAINT_TELEA)
            replacement_result = Image.fromarray(inpainted, mode='RGB')
            if working.mode == 'RGBA':
                replacement_result.putalpha(working.getchannel('A'))
            working = replacement_result
            applied = len(valid_rectangles)
        elif effect in {'blur', 'blur + noise'}:
            replacement = working.filter(ImageFilter.GaussianBlur(10))
        else:
            color = {
                'grey': (126, 126, 126),
                'grey + noise': (126, 126, 126),
                'black': (0, 0, 0),
                'white': (255, 255, 255),
            }[effect]
            replacement = Image.new(working.mode, working.size, color)

        if effect in {'blur + noise', 'grey + noise'}:
            import numpy as np

            rgb_replacement = replacement.convert('RGB')
            pixels = np.asarray(rgb_replacement, dtype=np.int16)
            noise = np.random.normal(0, 30, pixels.shape)
            noisy = np.clip(pixels + noise, 0, 255).astype(np.uint8)
            replacement = Image.fromarray(noisy, mode='RGB').filter(
                ImageFilter.GaussianBlur(1)
            )
            if working.mode == 'RGBA':
                replacement = replacement.convert('RGBA')

        if effect not in {
            'inpaint — ai (mi-gan)',
            'inpaint — basic (opencv)',
        }:
            applied = 0
            for clipped in valid_rectangles:
                box = (
                    clipped.x(),
                    clipped.y(),
                    clipped.x() + clipped.width(),
                    clipped.y() + clipped.height(),
                )
                working.paste(replacement.crop(box), box)
                applied += 1

        save_kwargs = {}
        if 'icc_profile' in original_info:
            save_kwargs['icc_profile'] = original_info['icc_profile']
        if 'exif' in original_info:
            save_kwargs['exif'] = original_info['exif']
        suffix = image_path.suffix.lower()
        if suffix in {'.jpg', '.jpeg'}:
            working = working.convert('RGB')
            save_kwargs.update(quality=95, optimize=True)
        elif suffix == '.png':
            save_kwargs['optimize'] = True
        working.save(image_path, format=original_format, **save_kwargs)
        return True, f'Applied {effect} to {applied} exclude marking(s) on {image_path.name}'
    except Exception as exc:
        return False, f'Failed to process {image_path.name}: {exc}'
