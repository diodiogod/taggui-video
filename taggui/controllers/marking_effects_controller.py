"""Apply exclude-marking effects directly to source images."""

from __future__ import annotations

import shutil
import tempfile
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QRect, QStandardPaths, QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QVBoxLayout,
)

from utils.image import ImageMarking
from utils.auto_crop import calculate_crop_avoiding_boxes
from utils.marking_effects import MARKING_EFFECTS, apply_exclude_effect
from utils.settings import DEFAULT_SETTINGS, settings
import utils.target_dimension as target_dimension


MIGAN_MODEL_URL = (
    'https://huggingface.co/andraniksargsyan/migan/resolve/'
    '1538c135034b8cfe7a8472f34d09c8a5a45b17a7/'
    'migan_pipeline_v2.onnx'
)
MIGAN_MODEL_SHA256 = (
    '6f1f3530a1a2324b19752018ce756088b07973cda8d7d890034ace5c8a48c40b'
)
MIGAN_MODEL_SIZE = 28_079_181


class MarkingEffectsController:
    """Orchestrate destructive marking effects and session undo groups."""

    _LAST_EFFECT_SETTING = 'last_marking_source_effect'

    def __init__(self, main_window):
        self.main_window = main_window
        self._undo_groups: list[dict] = []
        self._redo_groups: list[dict] = []

    @staticmethod
    def _canonical_effect(effect: str | None) -> str:
        candidate = str(effect or '').strip()
        for available in MARKING_EFFECTS:
            if available.casefold() == candidate.casefold():
                return available
        return MARKING_EFFECTS[0]

    def last_effect(self) -> str:
        """Return the remembered direct-action effect."""
        return self._canonical_effect(
            settings.value(
                self._LAST_EFFECT_SETTING,
                defaultValue=MARKING_EFFECTS[0],
                type=str,
            )
        )

    def remember_effect(self, effect: str | None) -> str:
        """Remember and return a valid effect name for future direct actions."""
        canonical = self._canonical_effect(effect)
        settings.setValue(self._LAST_EFFECT_SETTING, canonical)
        return canonical

    def _show_options(self) -> tuple[str, str, str, bool] | None:
        dialog = QDialog(self.main_window)
        dialog.setWindowTitle('Apply Markings to Source Images')
        layout = QVBoxLayout(dialog)
        warning = QLabel(
            'This modifies source image pixels. Markings themselves '
            'remain available after processing.'
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)
        form = QFormLayout()
        scope_combo = QComboBox()
        scope_combo.addItems(['Current image', 'Selected images', 'Loaded folder'])
        type_combo = QComboBox()
        type_combo.addItems(['All marking types', 'Exclude', 'Include', 'Hint'])
        effect_combo = QComboBox()
        effect_combo.addItems(list(MARKING_EFFECTS))
        effect_combo.setCurrentText(self.last_effect())
        undo_check = QCheckBox('Keep a session undo snapshot')
        undo_check.setChecked(True)
        undo_check.setToolTip(
            'Uses temporary disk space equal to the successfully modified images.'
        )
        form.addRow('Scope', scope_combo)
        form.addRow('Marking type', type_combo)
        form.addRow('Effect', effect_combo)
        form.addRow('', undo_check)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        self.remember_effect(effect_combo.currentText())
        return (
            scope_combo.currentText(),
            type_combo.currentText(),
            effect_combo.currentText(),
            undo_check.isChecked(),
        )

    def _scope_images(self, scope: str):
        model = self.main_window.image_list_model
        if scope == 'Current image':
            viewer = self.main_window.get_selection_target_viewer()
            if viewer.proxy_image_index.isValid():
                return [viewer.proxy_image_index.data(Qt.ItemDataRole.UserRole)]
            return []
        if scope == 'Selected images':
            return self.main_window.image_list.get_selected_image_batch()
        if getattr(model, '_paginated_mode', False):
            batch = model.create_paginated_domain_batch(filtered=False)
            if batch is not None:
                return batch
        return list(getattr(model, 'images', []))

    def _show_crop_options(self) -> dict | None:
        dialog = QDialog(self.main_window)
        dialog.setWindowTitle('Create Crops Avoiding Markings')
        layout = QVBoxLayout(dialog)
        explanation = QLabel(
            'Creates editable crop boxes without changing source pixels. '
            'Apply them later with the scissors tool.'
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        form = QFormLayout()
        scope_combo = QComboBox()
        scope_combo.addItems(['Current image', 'Selected images', 'Loaded folder'])
        type_combo = QComboBox()
        type_combo.addItems(['All marking types', 'Exclude', 'Include', 'Hint'])
        label_edit = QLineEdit()
        label_edit.setPlaceholderText('Optional, e.g. watermark')
        match_combo = QComboBox()
        match_combo.addItems(['Contains', 'Exact'])
        padding_spin = QDoubleSpinBox()
        padding_spin.setRange(0.0, 25.0)
        padding_spin.setDecimals(1)
        padding_spin.setValue(1.0)
        padding_spin.setSuffix('%')
        retained_spin = QDoubleSpinBox()
        retained_spin.setRange(1.0, 100.0)
        retained_spin.setDecimals(1)
        retained_spin.setValue(75.0)
        retained_spin.setSuffix('%')
        existing_combo = QComboBox()
        existing_combo.addItems(['Skip images with a crop', 'Replace existing crops'])
        form.addRow('Scope', scope_combo)
        form.addRow('Marking type', type_combo)
        form.addRow('Label filter', label_edit)
        form.addRow('Label match', match_combo)
        form.addRow('Padding', padding_spin)
        form.addRow('Minimum retained area', retained_spin)
        form.addRow('Existing crops', existing_combo)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return {
            'scope': scope_combo.currentText(),
            'marking_type': type_combo.currentText(),
            'label_filter': label_edit.text().strip(),
            'label_match': match_combo.currentText(),
            'padding_percent': padding_spin.value(),
            'minimum_retained_percent': retained_spin.value(),
            'replace_existing': existing_combo.currentIndex() == 1,
        }

    @staticmethod
    def _matching_marking_boxes(image, options: dict) -> list[list[float]]:
        selected_type = {
            'Exclude': ImageMarking.EXCLUDE,
            'Include': ImageMarking.INCLUDE,
            'Hint': ImageMarking.HINT,
        }.get(options['marking_type'])
        label_filter = str(options.get('label_filter') or '').casefold()
        exact = options.get('label_match') == 'Exact'
        boxes = []
        for marking in getattr(image, 'markings', []):
            if selected_type is not None and marking.type != selected_type:
                continue
            label = str(marking.label or '').casefold()
            if label_filter and (
                (exact and label != label_filter)
                or (not exact and label_filter not in label)
            ):
                continue
            rect = marking.rect.normalized()
            boxes.append([
                rect.left(), rect.top(),
                rect.left() + rect.width(), rect.top() + rect.height(),
            ])
        return boxes

    @staticmethod
    def _path_key(path) -> str:
        """Return a stable key for the same file across path representations."""
        try:
            return str(Path(path).resolve()).casefold()
        except OSError:
            return str(Path(path)).casefold()

    def create_crops_avoiding_markings(self):
        options = self._show_crop_options()
        if options is None:
            return
        model = self.main_window.image_list_model
        references = list(self._scope_images(options['scope']))
        progress = QProgressDialog(
            'Creating crops from markings…', 'Cancel', 0, len(references),
            self.main_window,
        )
        progress.setWindowTitle('Create Crops Avoiding Markings')
        progress.setMinimumDuration(250)
        generated = []
        skipped_existing = 0
        skipped_no_markings = 0
        skipped_unsafe = 0
        skipped_video = 0
        seen_paths: set[str] = set()
        for position, reference in enumerate(references, start=1):
            if progress.wasCanceled():
                progress.close()
                return
            image = model.resolve_image_reference(reference)
            if image is None:
                progress.setValue(position)
                continue
            loaded_row = model.get_loaded_row_for_path(image.path)
            if loaded_row >= 0:
                loaded_image = model.index(loaded_row, 0).data(
                    Qt.ItemDataRole.UserRole
                )
                if loaded_image is not None:
                    image = loaded_image
            path_key = self._path_key(image.path)
            if path_key in seen_paths:
                progress.setValue(position)
                continue
            seen_paths.add(path_key)
            if image.is_video:
                skipped_video += 1
            elif image.crop is not None and not options['replace_existing']:
                skipped_existing += 1
            else:
                boxes = self._matching_marking_boxes(image, options)
                if not boxes:
                    skipped_no_markings += 1
                else:
                    crop = calculate_crop_avoiding_boxes(
                        image.valid_dimensions(),
                        boxes,
                        padding_percent=options['padding_percent'],
                        minimum_retained_percent=options['minimum_retained_percent'],
                    )
                    if crop is None:
                        skipped_unsafe += 1
                    else:
                        generated.append((image, crop))
            progress.setValue(position)
            if position % 25 == 0:
                QApplication.processEvents()
        progress.close()
        if not generated:
            QMessageBox.information(
                self.main_window,
                'No Crops Created',
                'No matching markings produced a safe crop.\n\n'
                f'No matching markings: {skipped_no_markings}\n'
                f'Below retained-area limit: {skipped_unsafe}\n'
                f'Existing crops preserved: {skipped_existing}\n'
                f'Videos skipped: {skipped_video}',
            )
            return

        model.add_images_to_undo_stack(
            [image for image, _crop in generated],
            action_name='Create crops avoiding markings',
            should_ask_for_confirmation=False,
        )
        for image, crop in generated:
            image.crop = crop
            image.target_dimension = target_dimension.get(crop.size())
            image.thumbnail = None
            image.thumbnail_qimage = None
            # Notify exactly once. write_meta_to_disk() already emits
            # dataChanged by default; emitting it again here can re-enter the
            # viewer refresh path while the batch is still being written.
            model.write_meta_to_disk(image, notify=False)
            row = model.get_loaded_row_for_path(image.path)
            if row >= 0:
                model._notify_image_metadata_changed(
                    image,
                    refresh_filter=False,
                )

        viewer = self.main_window.get_selection_target_viewer()
        if viewer.proxy_image_index.isValid():
            displayed = viewer.proxy_image_index.data(Qt.ItemDataRole.UserRole)
            displayed_path_key = (
                self._path_key(displayed.path)
                if displayed is not None else None
            )
            matching = next(
                (entry for entry, _crop in generated
                 if displayed_path_key is not None
                 and self._path_key(entry.path) == displayed_path_key),
                None,
            )
            if matching is not None:
                if displayed is not matching:
                    displayed.crop = matching.crop
                    displayed.target_dimension = matching.target_dimension
                viewer.rebuild_marking_overlays(displayed)
        menu_manager = getattr(self.main_window, 'menu_manager', None)
        if menu_manager is not None:
            menu_manager.update_undo_and_redo_actions()
        QMessageBox.information(
            self.main_window,
            'Crops Created',
            f'Created {len(generated)} crop(s).\n\n'
            f'No matching markings: {skipped_no_markings}\n'
            f'Below retained-area limit: {skipped_unsafe}\n'
            f'Existing crops preserved: {skipped_existing}\n'
            f'Videos skipped: {skipped_video}\n\n'
            'Review the crop boxes, then use the scissors menu to apply them.',
        )

    @staticmethod
    def _file_sha256(path: Path) -> str:
        import hashlib

        digest = hashlib.sha256()
        with Path(path).open('rb') as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b''):
                digest.update(chunk)
        return digest.hexdigest()

    def _migan_model_path(self) -> Path:
        configured_root = settings.value(
            'models_directory_path',
            DEFAULT_SETTINGS['models_directory_path'],
            type=str,
        )
        if configured_root:
            root = Path(configured_root)
        else:
            root = Path(QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppLocalDataLocation
            )) / 'models'
        return root / 'inpainting' / 'migan_pipeline_v2.onnx'

    def _ensure_migan_model(self) -> Path | None:
        model_path = self._migan_model_path()
        if model_path.is_file():
            if self._file_sha256(model_path) == MIGAN_MODEL_SHA256:
                return model_path
            replace = QMessageBox.question(
                self.main_window,
                'Invalid MI-GAN Model',
                f'The existing MI-GAN model failed checksum verification:\n'
                f'{model_path}\n\nReplace it with the verified official model?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if replace != QMessageBox.StandardButton.Yes:
                return None

        consent = QMessageBox.question(
            self.main_window,
            'Download MI-GAN Inpainting Model',
            'AI inpainting uses the official MI-GAN ONNX pipeline.\n\n'
            'Download: 28.1 MB\nLicense: MIT\n'
            'Source: Picsart AI Research / Hugging Face\n\n'
            'The model is downloaded only once and loaded only when used. '
            'Continue?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if consent != QMessageBox.StandardButton.Yes:
            return None

        import urllib.request

        model_path.parent.mkdir(parents=True, exist_ok=True)
        partial_path = model_path.with_suffix('.onnx.part')
        progress = QProgressDialog(
            'Downloading MI-GAN model…',
            'Cancel',
            0,
            MIGAN_MODEL_SIZE,
            self.main_window,
        )
        progress.setWindowTitle('Download MI-GAN')
        progress.setMinimumDuration(0)
        try:
            downloaded = 0
            with urllib.request.urlopen(MIGAN_MODEL_URL, timeout=60) as response:
                with partial_path.open('wb') as output:
                    while True:
                        QApplication.processEvents()
                        if progress.wasCanceled():
                            return None
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        downloaded += len(chunk)
                        progress.setValue(min(downloaded, MIGAN_MODEL_SIZE))
            if self._file_sha256(partial_path) != MIGAN_MODEL_SHA256:
                QMessageBox.critical(
                    self.main_window,
                    'MI-GAN Download Failed',
                    'The downloaded model failed SHA-256 verification and was discarded.',
                )
                return None
            partial_path.replace(model_path)
            progress.setValue(MIGAN_MODEL_SIZE)
            return model_path
        except (OSError, TimeoutError) as exc:
            QMessageBox.critical(
                self.main_window,
                'MI-GAN Download Failed',
                f'Could not download the MI-GAN model:\n{exc}',
            )
            return None
        finally:
            progress.close()
            partial_path.unlink(missing_ok=True)

    def _refresh_modified_images(self, paths):
        model = self.main_window.image_list_model

        def normalize(path) -> str:
            try:
                return str(Path(path).resolve()).casefold()
            except OSError:
                return str(Path(path)).casefold()

        source_paths = [Path(path) for path in paths if path]
        normalized_paths = {normalize(path) for path in source_paths}
        for source_path in source_paths:
            row = model.get_loaded_row_for_path(source_path)
            if row < 0:
                continue
            index = model.index(row, 0)
            image = index.data(Qt.ItemDataRole.UserRole)
            if image is not None:
                refreshed = model.refresh_image_after_file_change(
                    image,
                    refresh_filter=False,
                )
                if not refreshed:
                    image.thumbnail = None
                    image.thumbnail_qimage = None
                    model.dataChanged.emit(
                        index,
                        index,
                        [Qt.ItemDataRole.DecorationRole, Qt.ItemDataRole.UserRole],
                    )
        viewer = self.main_window.get_selection_target_viewer()

        def reload_current_viewer():
            try:
                context_getter = getattr(viewer, 'get_live_image_context', None)
                if callable(context_getter):
                    proxy_index, _source_model, current = context_getter()
                else:
                    proxy_index = viewer.proxy_image_index
                    current = (
                        proxy_index.data(Qt.ItemDataRole.UserRole)
                        if proxy_index.isValid() else None
                    )
                if not proxy_index.isValid() or current is None:
                    return
                if normalize(current.path) not in normalized_paths:
                    return
                clear_cache = getattr(viewer, '_clear_static_image_render_cache', None)
                if callable(clear_cache):
                    clear_cache()
                viewer.load_image(proxy_index, True)
                viewer.view.viewport().update()
            except (RuntimeError, AttributeError):
                pass

        # Let dataChanged handlers finish first; then perform a complete image
        # reload so source-file undo/redo is visible without changing images.
        if normalized_paths:
            QTimer.singleShot(0, reload_current_viewer)
            image_list = getattr(self.main_window, 'image_list', None)
            list_view = getattr(image_list, 'list_view', None)
            if list_view is not None:
                list_view.viewport().update()
        menu_manager = getattr(self.main_window, 'menu_manager', None)
        if menu_manager is not None:
            menu_manager.update_undo_and_redo_actions()

    def apply_exclude_markings(self):
        options = self._show_options()
        if options is None:
            return
        scope, marking_type, effect, keep_undo = options
        effect = self.remember_effect(effect)
        model = self.main_window.image_list_model
        image_source = self._scope_images(scope)
        total = len(image_source)
        scan = QProgressDialog(
            'Finding images with matching markings…', 'Cancel', 0, total,
            self.main_window,
        )
        scan.setWindowTitle('Apply Markings')
        scan.setMinimumDuration(250)
        targets = []
        seen_paths = set()
        skipped_videos = 0
        for position, reference in enumerate(image_source, start=1):
            if scan.wasCanceled():
                scan.close()
                return
            image = model.resolve_image_reference(reference)
            if image is not None and image.path not in seen_paths:
                rectangles = [
                    QRect(
                        int(box[0]), int(box[1]),
                        int(box[2] - box[0]), int(box[3] - box[1]),
                    )
                    for box in self._matching_marking_boxes(image, {
                        'marking_type': marking_type,
                        'label_filter': '',
                        'label_match': 'Contains',
                    })
                ]
                if rectangles:
                    if image.is_video:
                        skipped_videos += 1
                    else:
                        targets.append((image, rectangles))
                        seen_paths.add(image.path)
            scan.setValue(position)
            if position % 25 == 0:
                QApplication.processEvents()
        scan.setValue(total)
        scan.close()

        if not targets:
            suffix = (
                f' ({skipped_videos} video(s) skipped.)'
                if skipped_videos else ''
            )
            QMessageBox.information(
                self.main_window,
                'No Matching Markings',
                f'No still images in this scope have matching markings.{suffix}',
            )
            return

        undo_note = (
            '\nSession undo snapshots will use approximately the same disk '
            'space as the affected images.' if keep_undo else ''
        )
        reply = QMessageBox.question(
            self.main_window,
            'Apply Markings - Destructive Operation',
            f'Apply “{effect}” inside {marking_type.lower()} on '
            f'{len(targets)} source image(s)?\n\n'
            'This changes the working files directly.'
            f'{undo_note}',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        migan_model_path = None
        if effect.casefold() == 'inpaint — AI (MI-GAN)'.casefold():
            migan_model_path = self._ensure_migan_model()
            if migan_model_path is None:
                return

        progress = QProgressDialog(
            'Applying markings…', 'Cancel', 0, len(targets),
            self.main_window,
        )
        progress.setWindowTitle('Apply Markings')
        progress.setMinimumDuration(0)
        snapshots: list[tuple[Path, Path]] = []
        failures: list[str] = []
        succeeded = 0
        canceled = False
        snapshot_root = Path(tempfile.gettempdir()) / 'taggui_marking_effect_undo'
        if keep_undo:
            snapshot_root.mkdir(exist_ok=True)

        for position, (image, rectangles) in enumerate(targets, start=1):
            QApplication.processEvents()
            if progress.wasCanceled():
                canceled = True
                break
            progress.setLabelText(f'Processing {image.path.name}…')
            snapshot = None
            if keep_undo:
                snapshot = snapshot_root / (
                    f'{uuid.uuid4().hex}_{image.path.name}'
                )
                try:
                    shutil.copy2(image.path, snapshot)
                except OSError as exc:
                    failures.append(
                        f'Could not create undo snapshot for {image.path.name}: {exc}'
                    )
                    progress.setValue(position)
                    continue
            success, message = apply_exclude_effect(
                Path(image.path),
                rectangles,
                effect,
                model_path=migan_model_path,
            )
            if success:
                succeeded += 1
                image.thumbnail = None
                image.thumbnail_qimage = None
                if snapshot is not None:
                    snapshots.append((Path(image.path), snapshot))
            else:
                failures.append(message)
                if snapshot is not None:
                    snapshot.unlink(missing_ok=True)
            progress.setValue(position)
        progress.close()

        if snapshots:
            self._undo_groups.append({
                'operation': f'Apply {effect} to markings',
                'snapshots': snapshots,
                'created_at_ns': time.monotonic_ns(),
            })
            self._clear_groups(self._redo_groups)
            while len(self._undo_groups) > 5:
                self._clear_groups([self._undo_groups.pop(0)])
        if succeeded:
            self._refresh_modified_images(
                image.path for image, _rectangles in targets
            )

        summary = f'Processed {succeeded} of {len(targets)} image(s).'
        if skipped_videos:
            summary += f'\nSkipped {skipped_videos} video(s).'
        if canceled:
            summary += '\nCanceled after preserving changes already completed.'
        if failures:
            summary += '\n\n' + '\n'.join(f'• {item}' for item in failures[:10])
        message_method = QMessageBox.warning if failures else QMessageBox.information
        message_method(self.main_window, 'Marking Effect Complete', summary)

    def apply_single_marking_effect(self, image_viewer, marking_item, effect: str):
        """Apply an effect immediately to one context-clicked marking."""
        effect = self.remember_effect(effect)
        context_getter = getattr(image_viewer, 'get_live_image_context', None)
        if callable(context_getter):
            proxy_index, _source_model, image = context_getter()
        else:
            proxy_index = getattr(image_viewer, 'proxy_image_index', None)
            image = (
                proxy_index.data(Qt.ItemDataRole.UserRole)
                if proxy_index is not None and proxy_index.isValid()
                else None
            )
        if proxy_index is None or not proxy_index.isValid() or image is None:
            return

        try:
            item_is_live = marking_item.scene() is image_viewer.scene
        except RuntimeError:
            item_is_live = False
        if not item_is_live:
            item_rect = None
            item_type = getattr(marking_item, 'rect_type', None)
            try:
                item_rect = marking_item.rect().toRect().normalized()
            except RuntimeError:
                pass
            replacement = None
            for candidate in list(image_viewer.marking_items):
                try:
                    if candidate.scene() is not image_viewer.scene:
                        continue
                    if candidate.rect_type != item_type:
                        continue
                    if (
                        item_rect is not None
                        and candidate.rect().toRect().normalized() != item_rect
                    ):
                        continue
                except RuntimeError:
                    continue
                replacement = candidate
                break
            marking_item = replacement
        if marking_item is None:
            return
        if image.is_video:
            QMessageBox.information(
                self.main_window,
                'Still Images Only',
                'Marking effects currently apply only to still images.',
            )
            return
        model_path = None
        if effect.casefold() == 'inpaint — AI (MI-GAN)'.casefold():
            model_path = self._ensure_migan_model()
            if model_path is None:
                return
        snapshot_root = Path(tempfile.gettempdir()) / 'taggui_marking_effect_undo'
        snapshot_root.mkdir(exist_ok=True)
        snapshot = snapshot_root / f'{uuid.uuid4().hex}_{image.path.name}'
        try:
            shutil.copy2(image.path, snapshot)
        except OSError as exc:
            QMessageBox.warning(
                self.main_window,
                'Could Not Create Undo Snapshot',
                str(exc),
            )
            return
        success, message = apply_exclude_effect(
            Path(image.path),
            [marking_item.rect().toRect()],
            effect,
            model_path=model_path,
        )
        if not success:
            snapshot.unlink(missing_ok=True)
            QMessageBox.warning(self.main_window, 'Marking Effect Failed', message)
            return
        self._undo_groups.append({
            'operation': f'Apply {effect} to marking',
            'snapshots': [(Path(image.path), snapshot)],
            'created_at_ns': time.monotonic_ns(),
        })
        self._clear_groups(self._redo_groups)
        while len(self._undo_groups) > 5:
            self._clear_groups([self._undo_groups.pop(0)])
        self._refresh_modified_images([image.path])

    @staticmethod
    def _clear_groups(groups: list[dict]):
        for group in groups:
            for _path, snapshot in group.get('snapshots', []):
                Path(snapshot).unlink(missing_ok=True)
        groups.clear()

    def can_undo(self) -> bool:
        return bool(self._undo_groups)

    def can_redo(self) -> bool:
        return bool(self._redo_groups)

    def clear_redo(self):
        self._clear_groups(self._redo_groups)

    def undo_timestamp(self) -> int:
        return (
            int(self._undo_groups[-1]['created_at_ns'])
            if self._undo_groups else 0
        )

    def redo_timestamp(self) -> int:
        return (
            int(self._redo_groups[-1]['created_at_ns'])
            if self._redo_groups else 0
        )

    def undo_action_name(self) -> str:
        return str(self._undo_groups[-1]['operation']) if self._undo_groups else ''

    def redo_action_name(self) -> str:
        return str(self._redo_groups[-1]['operation']) if self._redo_groups else ''

    def _restore_group(self, source_groups: list[dict], destination_groups: list[dict]):
        group = source_groups[-1]
        operation = str(group['operation'])
        snapshots = list(group['snapshots'])
        reverse_snapshots: list[tuple[Path, Path]] = []
        failures = []
        snapshot_root = Path(tempfile.gettempdir()) / 'taggui_marking_effect_undo'
        snapshot_root.mkdir(exist_ok=True)
        for image_path, snapshot in snapshots:
            reverse_snapshot = snapshot_root / (
                f'{uuid.uuid4().hex}_{Path(image_path).name}'
            )
            try:
                shutil.copy2(image_path, reverse_snapshot)
                shutil.copy2(snapshot, image_path)
                Path(snapshot).unlink(missing_ok=True)
                reverse_snapshots.append((Path(image_path), reverse_snapshot))
            except OSError as exc:
                reverse_snapshot.unlink(missing_ok=True)
                failures.append(f'{Path(image_path).name}: {exc}')
        source_groups.pop()
        if reverse_snapshots:
            destination_groups.append({
                'operation': operation,
                'snapshots': reverse_snapshots,
                'created_at_ns': int(group['created_at_ns']),
            })
        self._refresh_modified_images(
            image_path for image_path, _snapshot in reverse_snapshots
        )
        if failures:
            QMessageBox.warning(
                self.main_window,
                'History Restore Completed with Errors',
                '\n'.join(failures[:10]),
            )
        return operation, not failures

    def undo_last_effect(self, *, confirm: bool = True):
        if not self._undo_groups:
            QMessageBox.information(
                self.main_window,
                'No Effect Undo Available',
                'No marking-effect operation is available to undo in this session.',
            )
            return
        group = self._undo_groups[-1]
        if confirm:
            reply = QMessageBox.question(
                self.main_window,
                'Undo Marking Effect',
                f'Undo “{group["operation"]}” on '
                f'{len(group["snapshots"])} image(s)?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        operation, success = self._restore_group(
            self._undo_groups, self._redo_groups
        )
        if success and confirm:
            QMessageBox.information(
                self.main_window,
                'Undo Complete',
                f'Undid “{operation}”.',
            )

    def redo_last_effect(self):
        if not self._redo_groups:
            return
        self._restore_group(self._redo_groups, self._undo_groups)
