"""Controller for video editing operations."""

from pathlib import Path
from PySide6.QtWidgets import QMessageBox, QInputDialog, QProgressDialog
from PySide6.QtCore import Qt
from collections import deque

from utils.video_editor import VideoEditor
import subprocess
import json


class VideoEditingController:
    """Handles all video editing operations."""

    def __init__(self, main_window):
        """Initialize controller with reference to main window."""
        self.main_window = main_window
        # Undo/redo stacks: store (video_path, operation_name, undo_snapshot_path) tuples
        self.undo_stack = deque(maxlen=10)  # Keep last 10 edits
        self.redo_stack = []

    def _save_undo_snapshot(self, video_path: Path, operation_name: str):
        """Save current video state for undo before editing."""
        import shutil
        import time
        import tempfile

        # Create undo snapshots directory in system temp
        temp_base = Path(tempfile.gettempdir()) / 'taggui_undo'
        temp_base.mkdir(exist_ok=True)

        # Create unique snapshot filename with timestamp
        timestamp = int(time.time() * 1000)
        snapshot_name = f"{video_path.stem}_undo_{timestamp}{video_path.suffix}"
        snapshot_path = temp_base / snapshot_name

        try:
            # Copy current video to snapshot
            shutil.copy2(str(video_path), str(snapshot_path))

            # Add to undo stack
            self.undo_stack.append((video_path, operation_name, snapshot_path))

            # Clear redo stack (new edit invalidates redo history)
            self._clear_redo_stack()

            # Clean up old snapshots (keep only what's in undo stack)
            self._cleanup_old_snapshots(video_path)

        except Exception as e:
            print(f"Failed to create undo snapshot: {e}")

    def _clear_redo_stack(self):
        """Clear redo stack and delete redo snapshot files."""
        import os
        for video_path, operation_name, snapshot_path in self.redo_stack:
            try:
                if snapshot_path.exists():
                    os.remove(snapshot_path)
            except:
                pass
        self.redo_stack.clear()

    def _cleanup_old_snapshots(self, video_path: Path):
        """Remove undo snapshots that are no longer in the undo stack."""
        import os
        import tempfile

        temp_base = Path(tempfile.gettempdir()) / 'taggui_undo'
        if not temp_base.exists():
            return

        # Get all snapshots currently in undo stack for this video
        active_snapshots = {str(s) for v, o, s in self.undo_stack if v == video_path}

        # Delete snapshots that aren't in the stack
        try:
            for file in temp_base.iterdir():
                if file.is_file() and file.stem.startswith(video_path.stem + '_undo_'):
                    if str(file) not in active_snapshots:
                        os.remove(file)
        except:
            pass

    def extract_video_range(self):
        """Extract the marked range, replacing the original video (creates backup)."""
        video_player = self.main_window.image_viewer.video_player
        video_controls = self.main_window.image_viewer.video_controls

        # Check if we have a video loaded
        if not video_player.video_path:
            QMessageBox.warning(self.main_window, "No Video", "No video is currently loaded.")
            return

        # Check if markers are set
        loop_range = video_controls.get_loop_range()
        if not loop_range:
            QMessageBox.warning(self.main_window, "No Markers", "Please set loop markers first.")
            return

        start_frame, end_frame = loop_range
        fps = video_player.get_fps()
        input_path = Path(video_player.video_path)

        # Confirm action
        reply = QMessageBox.question(
            self.main_window, "Extract Range",
            f"Extract frames {start_frame}-{end_frame} (discard rest)?\n\n"
            f"Original will be saved as {input_path.name}.backup",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        # Save undo snapshot before editing
        self._save_undo_snapshot(input_path, f"Extract frames {start_frame}-{end_frame}")

        # Extract range (overwrites original, creates backup)
        success, message = VideoEditor.extract_range(
            input_path, input_path,
            start_frame, end_frame, fps
        )

        if success:
            QMessageBox.information(self.main_window, "Success", message)
            self.main_window.reload_directory()
        else:
            QMessageBox.critical(self.main_window, "Error", message)

    def remove_video_range(self):
        """Remove the marked range from the video."""
        video_player = self.main_window.image_viewer.video_player
        video_controls = self.main_window.image_viewer.video_controls

        if not video_player.video_path:
            QMessageBox.warning(self.main_window, "No Video", "No video is currently loaded.")
            return

        loop_range = video_controls.get_loop_range()
        if not loop_range:
            QMessageBox.warning(self.main_window, "No Markers", "Please set loop markers first.")
            return

        start_frame, end_frame = loop_range
        fps = video_player.get_fps()
        input_path = Path(video_player.video_path)

        # Confirm action
        reply = QMessageBox.question(
            self.main_window, "Remove Range",
            f"Remove frames {start_frame}-{end_frame}?\n\n"
            f"Original will be saved as {input_path.name}.backup",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        # Save undo snapshot before editing
        self._save_undo_snapshot(input_path, f"Remove frames {start_frame}-{end_frame}")

        # Remove range (overwrites original, creates backup)
        success, message = VideoEditor.remove_range(
            input_path, input_path,
            start_frame, end_frame, fps
        )

        if success:
            QMessageBox.information(self.main_window, "Success", message)
            self.main_window.reload_directory()
        else:
            QMessageBox.critical(self.main_window, "Error", message)

    def remove_video_frame(self):
        """Remove the current frame from the video."""
        video_player = self.main_window.image_viewer.video_player

        if not video_player.video_path:
            QMessageBox.warning(self.main_window, "No Video", "No video is currently loaded.")
            return

        current_frame = video_player.get_current_frame_number()
        fps = video_player.get_fps()
        input_path = Path(video_player.video_path)

        # Confirm action
        reply = QMessageBox.question(
            self.main_window, "Remove Frame",
            f"Remove frame {current_frame}?\n\n"
            f"Original will be saved as {input_path.name}.backup",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        # Save undo snapshot before editing
        self._save_undo_snapshot(input_path, f"Remove frame {current_frame}")

        # Remove frame
        success, message = VideoEditor.remove_frame(
            input_path, input_path,
            current_frame, fps
        )

        if success:
            QMessageBox.information(self.main_window, "Success", message)
            self.main_window.reload_directory()
        else:
            QMessageBox.critical(self.main_window, "Error", message)

    def repeat_video_frame(self):
        """Repeat the current frame multiple times."""
        video_player = self.main_window.image_viewer.video_player

        if not video_player.video_path:
            QMessageBox.warning(self.main_window, "No Video", "No video is currently loaded.")
            return

        current_frame = video_player.get_current_frame_number()
        fps = video_player.get_fps()
        input_path = Path(video_player.video_path)

        # Ask how many times to repeat
        max_frame = video_player.get_total_frames() - 1
        is_last_frame = current_frame == max_frame
        frame_desc = f"{current_frame} (last)" if is_last_frame else str(current_frame)
        repeat_count, ok = QInputDialog.getInt(
            self.main_window, "Repeat Frame",
            f"How many times to repeat frame {frame_desc}?",
            value=1, minValue=1, maxValue=100
        )

        if not ok:
            return

        # Confirm action
        reply = QMessageBox.question(
            self.main_window, "Repeat Frame",
            f"Repeat frame {current_frame} {repeat_count} times?\n\n"
            f"Original will be saved as {input_path.name}.backup",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        # Save undo snapshot before editing
        self._save_undo_snapshot(input_path, f"Repeat frame {current_frame} {repeat_count}x")

        # Repeat frame
        success, message = VideoEditor.repeat_frame(
            input_path, input_path,
            current_frame, repeat_count, fps
        )

        if success:
            QMessageBox.information(self.main_window, "Success", message)
            self.main_window.reload_directory()
        else:
            QMessageBox.critical(self.main_window, "Error", message)

    def fix_video_frame_count(self):
        """Fix video frame count to follow N*4+1 rule for selected videos."""
        # Get selected videos from image list
        selected_indices = self.main_window.image_list.get_selected_image_indices()

        if not selected_indices:
            QMessageBox.warning(self.main_window, "No Selection", "Please select one or more videos to fix.")
            return

        # Filter to only videos
        video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.webm'}
        video_paths = []
        for idx in selected_indices:
            image = self.main_window.image_list_model.data(idx, Qt.ItemDataRole.UserRole)
            if image.path.suffix.lower() in video_extensions:
                video_paths.append(image.path)

        if not video_paths:
            QMessageBox.warning(self.main_window, "No Videos", "No videos in selection.")
            return

        # Ask for method preference once for all videos
        choice, ok = QInputDialog.getItem(
            self.main_window, "Fix Frame Count",
            f"Fix {len(video_paths)} video(s) to N*4+1 pattern.\n\nMethod:",
            ["Auto (use last frame)", "Auto (use first frame)"], 0, False
        )

        if not ok:
            return

        repeat_last = "last" in choice

        # Confirm batch operation
        reply = QMessageBox.question(
            self.main_window, "Fix Frame Count",
            f"Fix frame count for {len(video_paths)} video(s)?\n\n"
            f"Originals will be saved as .backup files",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        # Process videos with progress dialog
        progress = QProgressDialog("Fixing video frame counts...", "Cancel", 0, len(video_paths), self.main_window)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)

        success_count = 0
        error_count = 0
        errors = []

        for i, video_path in enumerate(video_paths):
            if progress.wasCanceled():
                break

            progress.setLabelText(f"Processing {video_path.name}...")
            progress.setValue(i)

            # Get FPS from video
            probe_cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', str(video_path)]
            try:
                probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
                probe_data = json.loads(probe_result.stdout)
                fps = None
                for stream in probe_data.get('streams', []):
                    if stream.get('codec_type') == 'video':
                        fps_str = stream.get('r_frame_rate', '0/1')
                        num, denom = map(float, fps_str.split('/'))
                        fps = num / denom if denom != 0 else 0
                        break

                if not fps:
                    errors.append(f"{video_path.name}: Could not determine FPS")
                    error_count += 1
                    continue

                # Fix frame count
                success, message = VideoEditor.fix_frame_count_to_n4_plus_1(
                    video_path, video_path, fps, repeat_last, None
                )

                if success:
                    success_count += 1
                    if success_count == 1:  # Track first successful edit for undo
                        self.last_edited_video = video_path
                else:
                    errors.append(f"{video_path.name}: {message}")
                    error_count += 1

            except Exception as e:
                errors.append(f"{video_path.name}: {str(e)}")
                error_count += 1

        progress.setValue(len(video_paths))

        # Show results
        result_msg = f"Processed {len(video_paths)} video(s):\n"
        result_msg += f"✓ Success: {success_count}\n"
        result_msg += f"✗ Errors: {error_count}"

        if errors:
            result_msg += "\n\nErrors:\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                result_msg += f"\n... and {len(errors) - 10} more"

        if error_count > 0:
            QMessageBox.warning(self.main_window, "Batch Fix Complete", result_msg)
        else:
            QMessageBox.information(self.main_window, "Success", result_msg)

        # Auto-reload directory to show changes
        self.main_window.reload_directory()

    def fix_all_folder_frame_count(self):
        """Fix N*4+1 frame count for all videos in the current folder."""
        if not self.main_window.directory_path:
            QMessageBox.warning(self.main_window, "No Directory", "No directory is loaded.")
            return

        # Find all videos in directory
        video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.webm'}
        video_paths = [f for f in self.main_window.directory_path.iterdir()
                      if f.is_file() and f.suffix.lower() in video_extensions]

        if not video_paths:
            QMessageBox.warning(self.main_window, "No Videos", "No videos found in current directory.")
            return

        # Ask for method preference
        choice, ok = QInputDialog.getItem(
            self.main_window, "Fix All Videos",
            f"Fix {len(video_paths)} video(s) in folder to N*4+1 pattern.\n\nMethod:",
            ["Auto (use last frame)", "Auto (use first frame)"], 0, False
        )

        if not ok:
            return

        repeat_last = "last" in choice

        # Confirm batch operation
        reply = QMessageBox.question(
            self.main_window, "Fix All Videos",
            f"Fix frame count for all {len(video_paths)} video(s) in folder?\n\n"
            f"Originals will be saved as .backup files",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        # Process videos with progress dialog
        progress = QProgressDialog("Fixing video frame counts...", "Cancel", 0, len(video_paths), self.main_window)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)

        success_count = 0
        skip_count = 0
        error_count = 0
        errors = []

        for i, video_path in enumerate(video_paths):
            if progress.wasCanceled():
                break

            progress.setLabelText(f"Processing {video_path.name}...")
            progress.setValue(i)

            # Get FPS from video
            probe_cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', str(video_path)]
            try:
                probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
                probe_data = json.loads(probe_result.stdout)
                fps = None
                for stream in probe_data.get('streams', []):
                    if stream.get('codec_type') == 'video':
                        fps_str = stream.get('r_frame_rate', '0/1')
                        num, denom = map(float, fps_str.split('/'))
                        fps = num / denom if denom != 0 else 0
                        break

                if not fps:
                    errors.append(f"{video_path.name}: Could not determine FPS")
                    error_count += 1
                    continue

                # Fix frame count
                success, message = VideoEditor.fix_frame_count_to_n4_plus_1(
                    video_path, video_path, fps, repeat_last, None
                )

                if success:
                    if "already" in message.lower():
                        skip_count += 1
                    else:
                        success_count += 1
                else:
                    errors.append(f"{video_path.name}: {message}")
                    error_count += 1

            except Exception as e:
                errors.append(f"{video_path.name}: {str(e)}")
                error_count += 1

        progress.setValue(len(video_paths))

        # Show results
        result_msg = f"Processed {len(video_paths)} video(s):\n"
        result_msg += f"✓ Fixed: {success_count}\n"
        result_msg += f"⊘ Already valid: {skip_count}\n"
        result_msg += f"✗ Errors: {error_count}"

        if errors:
            result_msg += "\n\nErrors:\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                result_msg += f"\n... and {len(errors) - 10} more"

        if error_count > 0:
            QMessageBox.warning(self.main_window, "Batch Fix Complete", result_msg)
        else:
            QMessageBox.information(self.main_window, "Success", result_msg)

        # Auto-reload directory to show changes
        self.main_window.reload_directory()

    def fix_sar_selected(self):
        """Fix non-square pixels (SAR) for selected videos."""
        # Get selected videos from image list
        selected_indices = self.main_window.image_list.get_selected_image_indices()

        if not selected_indices:
            QMessageBox.warning(self.main_window, "No Selection", "Please select one or more videos to fix.")
            return

        # Filter to only videos
        video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.webm'}
        video_paths = []
        for idx in selected_indices:
            image = self.main_window.image_list_model.data(idx, Qt.ItemDataRole.UserRole)
            if image.path.suffix.lower() in video_extensions:
                video_paths.append(image.path)

        if not video_paths:
            QMessageBox.warning(self.main_window, "No Videos", "No videos in selection.")
            return

        # Scan for non-square SAR videos
        non_square_videos = []
        for video_path in video_paths:
            sar_num, sar_den, dims = VideoEditor.check_sar(video_path)
            if sar_num and sar_den and sar_num != sar_den:
                non_square_videos.append((video_path, sar_num, sar_den))

        if not non_square_videos:
            QMessageBox.information(self.main_window, "No Issues", "All selected videos have square pixels (SAR 1:1).")
            return

        # Confirm batch operation
        sar_list = "\n".join([f"• {v[0].name} (SAR {v[1]}:{v[2]})" for v in non_square_videos[:5]])
        if len(non_square_videos) > 5:
            sar_list += f"\n... and {len(non_square_videos) - 5} more"

        reply = QMessageBox.question(
            self.main_window, "Fix SAR",
            f"Found {len(non_square_videos)} video(s) with non-square pixels:\n\n{sar_list}\n\n"
            f"Fix these videos?\nOriginals will be saved as .backup files",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        # Process videos with progress dialog
        progress = QProgressDialog("Fixing SAR...", "Cancel", 0, len(non_square_videos), self.main_window)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)

        success_count, error_count, errors = VideoEditor.batch_fix_sar(
            [v[0] for v in non_square_videos],
            progress_callback=lambda current, total, name: (
                progress.setLabelText(f"Processing {name}..."),
                progress.setValue(current),
                progress.wasCanceled()
            )
        )

        if success_count > 0:  # Track first successful edit for undo
            self.last_edited_video = non_square_videos[0][0]

        progress.setValue(len(non_square_videos))

        # Show results
        result_msg = f"Processed {len(non_square_videos)} video(s):\n"
        result_msg += f"✓ Success: {success_count}\n"
        result_msg += f"✗ Errors: {error_count}"

        if errors:
            result_msg += "\n\nErrors:\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                result_msg += f"\n... and {len(errors) - 10} more"

        if error_count > 0:
            QMessageBox.warning(self.main_window, "SAR Fix Complete", result_msg)
        else:
            QMessageBox.information(self.main_window, "Success", result_msg)

        # Auto-reload directory to show changes
        self.main_window.reload_directory()

    def fix_all_sar_folder(self):
        """Fix SAR for all videos in the current folder."""
        if not self.main_window.directory_path:
            QMessageBox.warning(self.main_window, "No Directory", "No directory is loaded.")
            return

        # Find all videos in directory
        video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.webm'}
        video_paths = [f for f in self.main_window.directory_path.iterdir()
                      if f.is_file() and f.suffix.lower() in video_extensions]

        if not video_paths:
            QMessageBox.warning(self.main_window, "No Videos", "No videos found in current directory.")
            return

        # Scan for non-square SAR videos
        non_square_videos = VideoEditor.scan_directory_for_non_square_sar(
            self.main_window.directory_path, video_extensions
        )

        if not non_square_videos:
            QMessageBox.information(self.main_window, "No Issues",
                f"All {len(video_paths)} video(s) in folder have square pixels (SAR 1:1).")
            return

        # Confirm batch operation
        sar_list = "\n".join([f"• {v[0].name} (SAR {v[1]}:{v[2]})" for v in non_square_videos[:5]])
        if len(non_square_videos) > 5:
            sar_list += f"\n... and {len(non_square_videos) - 5} more"

        reply = QMessageBox.question(
            self.main_window, "Fix All SAR",
            f"Found {len(non_square_videos)}/{len(video_paths)} video(s) with non-square pixels:\n\n{sar_list}\n\n"
            f"Fix these videos?\nOriginals will be saved as .backup files",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        # Process videos with progress dialog
        progress = QProgressDialog("Fixing SAR...", "Cancel", 0, len(non_square_videos), self.main_window)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)

        success_count, error_count, errors = VideoEditor.batch_fix_sar(
            [v[0] for v in non_square_videos],
            progress_callback=lambda current, total, name: (
                progress.setLabelText(f"Processing {name}..."),
                progress.setValue(current),
                progress.wasCanceled()
            )
        )

        progress.setValue(len(non_square_videos))

        # Show results
        result_msg = f"Processed {len(non_square_videos)} video(s):\n"
        result_msg += f"✓ Success: {success_count}\n"
        result_msg += f"✗ Errors: {error_count}"

        if errors:
            result_msg += "\n\nErrors:\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                result_msg += f"\n... and {len(errors) - 10} more"

        if error_count > 0:
            QMessageBox.warning(self.main_window, "SAR Fix Complete", result_msg)
        else:
            QMessageBox.information(self.main_window, "Success", result_msg)

        # Auto-reload directory to show changes
        self.main_window.reload_directory()

    def apply_speed_change(self):
        """Apply speed change to current video based on speed slider value."""
        video_player = self.main_window.image_viewer.video_player
        video_controls = self.main_window.image_viewer.video_controls

        if not video_player.video_path:
            QMessageBox.warning(self.main_window, "No Video", "No video is currently loaded.")
            return

        # Get current speed from controls
        current_speed = video_controls._extended_speed

        input_path = Path(video_player.video_path)
        fps = video_player.get_fps()

        # Calculate new frame count for preview
        current_frames = video_controls._current_frame_count

        # Ask for speed and optional FPS override
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QDoubleSpinBox, QDialogButtonBox, QCheckBox, QHBoxLayout

        dialog = QDialog(self.main_window)
        dialog.setWindowTitle("Apply Speed Change")
        layout = QVBoxLayout(dialog)

        # Current video info
        info_label = QLabel(f"Current video: {current_frames} frames @ {fps:.2f} fps")
        layout.addWidget(info_label)

        # Speed multiplier input
        speed_layout = QHBoxLayout()
        speed_layout.addWidget(QLabel("Speed multiplier:"))
        speed_spinbox = QDoubleSpinBox()
        speed_spinbox.setMinimum(0.2)
        speed_spinbox.setMaximum(5.0)
        speed_spinbox.setValue(current_speed)
        speed_spinbox.setSingleStep(0.1)
        speed_spinbox.setDecimals(2)
        speed_spinbox.setSuffix('x')
        speed_layout.addWidget(speed_spinbox)
        layout.addLayout(speed_layout)

        # Preview label (updates when speed changes)
        preview_label = QLabel()
        layout.addWidget(preview_label)

        def update_preview():
            speed = speed_spinbox.value()
            target_fps = fps_spinbox.value() if fps_checkbox.isChecked() else fps

            # Calculate new duration based on speed
            original_duration = current_frames / fps if fps > 0 else 0
            new_duration = original_duration / speed

            # Calculate new frame count based on target FPS and new duration
            new_frames = max(1, int(new_duration * target_fps))

            preview_label.setText(f"Result: {new_frames} frames @ {target_fps:.2f} fps | {new_duration:.1f}s")

        speed_spinbox.valueChanged.connect(update_preview)

        # FPS override option
        fps_checkbox = QCheckBox("Override FPS (for LoRA training, recommended: 16 fps)")
        fps_checkbox.setChecked(False)
        layout.addWidget(fps_checkbox)

        fps_spinbox = QDoubleSpinBox()
        fps_spinbox.setMinimum(1.0)
        fps_spinbox.setMaximum(120.0)
        fps_spinbox.setValue(16.0)  # Default suggestion for LoRA training
        fps_spinbox.setSuffix(' fps')
        fps_spinbox.setEnabled(False)
        layout.addWidget(fps_spinbox)

        fps_checkbox.toggled.connect(fps_spinbox.setEnabled)
        fps_checkbox.toggled.connect(update_preview)
        fps_spinbox.valueChanged.connect(update_preview)

        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        # Initialize preview
        update_preview()

        if dialog.exec() != QDialog.Accepted:
            return

        # Get final values
        final_speed = speed_spinbox.value()
        target_fps = fps_spinbox.value() if fps_checkbox.isChecked() else None

        # Check if speed is 1.0x (no change needed)
        if abs(final_speed - 1.0) < 0.01 and target_fps is None:
            QMessageBox.information(self.main_window, "No Change", "Speed is 1.0x and no FPS override. No changes needed.")
            return

        # Confirm action
        fps_msg = f"\nTarget FPS: {target_fps:.2f}" if target_fps else ""

        reply = QMessageBox.question(
            self.main_window, "Apply Speed Change",
            f"Apply speed change {final_speed:.2f}x to video?{fps_msg}\n\n"
            f"Original will be saved as {input_path.name}.backup",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        # Apply speed change
        success, message = VideoEditor.change_speed(
            input_path, input_path,
            final_speed, target_fps
        )

        if success:
            self.last_edited_video = input_path  # Track for undo
            QMessageBox.information(self.main_window, "Success", message)
            self.main_window.reload_directory()
        else:
            QMessageBox.critical(self.main_window, "Error", message)

    def undo_last_edit(self):
        """Undo the last video editing operation."""
        import shutil
        import time

        if not self.undo_stack:
            QMessageBox.information(self.main_window, "No Undo Available", "No recent video edits to undo.")
            return

        # Get last edit from undo stack
        video_path, operation_name, snapshot_path = self.undo_stack.pop()

        if not snapshot_path.exists():
            QMessageBox.warning(
                self.main_window, "Snapshot Not Found",
                f"Undo snapshot not found:\n{snapshot_path.name}\n\nCannot undo."
            )
            return

        # Confirm undo
        reply = QMessageBox.question(
            self.main_window, "Undo Video Edit",
            f"Undo: {operation_name}\n\n"
            f"Video: {video_path.name}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            # Put it back on the stack
            self.undo_stack.append((video_path, operation_name, snapshot_path))
            return

        try:
            # Save current version for redo
            import tempfile
            temp_base = Path(tempfile.gettempdir()) / 'taggui_undo'
            temp_base.mkdir(exist_ok=True)
            timestamp = int(time.time() * 1000)
            redo_snapshot = temp_base / f"{video_path.stem}_redo_{timestamp}{video_path.suffix}"
            shutil.copy2(str(video_path), str(redo_snapshot))

            # Restore from snapshot
            shutil.copy2(str(snapshot_path), str(video_path))

            # Move to redo stack
            self.redo_stack.append((video_path, operation_name, redo_snapshot))

            QMessageBox.information(self.main_window, "Undo Complete", f"Undone: {operation_name}")
            self.main_window.reload_directory()
        except Exception as e:
            QMessageBox.critical(self.main_window, "Undo Error", f"Failed to undo:\n{str(e)}")

    def redo_last_edit(self):
        """Redo the last undone video editing operation."""
        import shutil
        import time

        if not self.redo_stack:
            QMessageBox.information(self.main_window, "No Redo Available", "No recent undos to redo.")
            return

        # Get last redo from stack
        video_path, operation_name, redo_snapshot = self.redo_stack.pop()

        if not redo_snapshot.exists():
            QMessageBox.warning(
                self.main_window, "Redo Snapshot Not Found",
                f"Redo snapshot not found:\n{redo_snapshot.name}\n\nCannot redo."
            )
            return

        # Confirm redo
        reply = QMessageBox.question(
            self.main_window, "Redo Video Edit",
            f"Redo: {operation_name}\n\n"
            f"Video: {video_path.name}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            # Put it back on the stack
            self.redo_stack.append((video_path, operation_name, redo_snapshot))
            return

        try:
            # Save current version for undo
            import tempfile
            temp_base = Path(tempfile.gettempdir()) / 'taggui_undo'
            temp_base.mkdir(exist_ok=True)
            timestamp = int(time.time() * 1000)
            undo_snapshot = temp_base / f"{video_path.stem}_undo_{timestamp}{video_path.suffix}"
            shutil.copy2(str(video_path), str(undo_snapshot))

            # Restore from redo snapshot
            shutil.copy2(str(redo_snapshot), str(video_path))

            # Move back to undo stack
            self.undo_stack.append((video_path, operation_name, undo_snapshot))

            QMessageBox.information(self.main_window, "Redo Complete", f"Redone: {operation_name}")
            self.main_window.reload_directory()
        except Exception as e:
            QMessageBox.critical(self.main_window, "Redo Error", f"Failed to redo:\n{str(e)}")
