"""Apply exclude-marking effects directly to source images."""

from __future__ import annotations

import shutil
import tempfile
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QVBoxLayout,
)

from utils.image import ImageMarking
from utils.marking_effects import MARKING_EFFECTS, apply_exclude_effect
from utils.settings import DEFAULT_SETTINGS, settings


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

    def __init__(self, main_window):
        self.main_window = main_window
        self._undo_groups: list[dict] = []
        self._redo_groups: list[dict] = []

    def _show_options(self) -> tuple[str, str, bool] | None:
        dialog = QDialog(self.main_window)
        dialog.setWindowTitle('Apply Exclude Markings to Source Images')
        layout = QVBoxLayout(dialog)
        warning = QLabel(
            'This modifies source image pixels. Exclude markings themselves '
            'remain available after processing.'
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)
        form = QFormLayout()
        scope_combo = QComboBox()
        scope_combo.addItems(['Current image', 'Selected images', 'Loaded folder'])
        effect_combo = QComboBox()
        effect_combo.addItems(list(MARKING_EFFECTS))
        effect_combo.setCurrentText('inpaint — AI (MI-GAN)')
        undo_check = QCheckBox('Keep a session undo snapshot')
        undo_check.setChecked(True)
        undo_check.setToolTip(
            'Uses temporary disk space equal to the successfully modified images.'
        )
        form.addRow('Scope', scope_combo)
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
        return (
            scope_combo.currentText(),
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
        changed_indexes = []
        normalized_paths = {str(Path(path)) for path in paths}
        for path in normalized_paths:
            row = model.get_loaded_row_for_path(Path(path))
            if row < 0:
                continue
            index = model.index(row, 0)
            image = index.data(Qt.ItemDataRole.UserRole)
            if image is not None:
                image.thumbnail = None
                image.thumbnail_qimage = None
            changed_indexes.append(index)
        for index in changed_indexes:
            model.dataChanged.emit(
                index,
                index,
                [Qt.ItemDataRole.DecorationRole, Qt.ItemDataRole.UserRole],
            )
        viewer = self.main_window.get_selection_target_viewer()
        if viewer.proxy_image_index.isValid():
            current = viewer.proxy_image_index.data(Qt.ItemDataRole.UserRole)
            if current is not None and str(current.path) in normalized_paths:
                viewer.load_image(viewer.proxy_image_index)
        menu_manager = getattr(self.main_window, 'menu_manager', None)
        if menu_manager is not None:
            menu_manager.update_undo_and_redo_actions()

    def apply_exclude_markings(self):
        options = self._show_options()
        if options is None:
            return
        scope, effect, keep_undo = options
        model = self.main_window.image_list_model
        image_source = self._scope_images(scope)
        total = len(image_source)
        scan = QProgressDialog(
            'Finding images with exclude markings…', 'Cancel', 0, total,
            self.main_window,
        )
        scan.setWindowTitle('Apply Exclude Markings')
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
                    marking.rect
                    for marking in image.markings
                    if marking.type == ImageMarking.EXCLUDE
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
                'No Exclude Markings',
                f'No still images in this scope have exclude markings.{suffix}',
            )
            return

        undo_note = (
            '\nSession undo snapshots will use approximately the same disk '
            'space as the affected images.' if keep_undo else ''
        )
        reply = QMessageBox.question(
            self.main_window,
            'Apply Exclude Markings - Destructive Operation',
            f'Apply “{effect}” inside exclude markings on '
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
            'Applying exclude markings…', 'Cancel', 0, len(targets),
            self.main_window,
        )
        progress.setWindowTitle('Apply Exclude Markings')
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
                'operation': f'Apply {effect} to exclude markings',
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
        message_method(self.main_window, 'Exclude Marking Effect Complete', summary)

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
