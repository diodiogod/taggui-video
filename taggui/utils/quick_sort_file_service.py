"""Bundle-aware file operations for the Quick Sort workflow."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import stat

from utils.ideogram_caption import ideogram_caption_path
from utils.sidecar import (
    legacy_json_sidecar_path,
    taggui_sidecar_path,
)


class QuickSortFileError(OSError):
    """Raised when a Quick Sort file operation cannot be completed safely."""


class QuickSortCollisionError(QuickSortFileError):
    """Raised when a destination bundle already exists."""


class QuickSortAmbiguousSidecarError(QuickSortFileError):
    """Raised when multiple sibling media files appear to share sidecars."""


@dataclass(frozen=True)
class QuickSortDestinationIdentity:
    """Non-following identity used to prove a copied output is still ours."""

    device: int
    inode: int
    mode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    symlink_target: str | None = None

    @classmethod
    def capture(cls, path: Path) -> "QuickSortDestinationIdentity":
        path_stat = os.lstat(path)
        link_target = os.readlink(path) if stat.S_ISLNK(path_stat.st_mode) else None
        return cls(
            device=int(path_stat.st_dev),
            inode=int(path_stat.st_ino),
            mode=int(path_stat.st_mode),
            size=int(path_stat.st_size),
            mtime_ns=int(path_stat.st_mtime_ns),
            ctime_ns=int(path_stat.st_ctime_ns),
            symlink_target=link_target,
        )


@dataclass(frozen=True)
class QuickSortFileOperation:
    mode: str
    source: Path
    destination: Path
    bundle_pairs: tuple[tuple[Path, Path], ...]
    destination_identities: tuple[
        tuple[Path, QuickSortDestinationIdentity], ...
    ] = ()

    @property
    def action_name(self) -> str:
        verb = "Move" if self.mode == "move" else "Copy"
        return f"{verb} to {self.destination.parent.name}"


@dataclass(frozen=True)
class QuickSortFileResult:
    operation: QuickSortFileOperation | None = None
    skipped: bool = False
    message: str = ""


class QuickSortFileService:
    """Perform reversible media + sidecar bundle operations without overwrites."""

    # Backup files intentionally stay with their original media. This matches the
    # existing move/copy workflows: backups are recovery artifacts, not sidecars.
    _COMPANION_BUILDERS = (
        lambda path: Path(path).with_suffix(".txt"),
        taggui_sidecar_path,
        legacy_json_sidecar_path,
        ideogram_caption_path,
    )

    @staticmethod
    def _absolute_path(path: Path) -> Path:
        """Return an absolute path without resolving a symlink to its target."""
        return Path(os.path.abspath(os.fspath(path)))

    @staticmethod
    def _path_exists(path: Path) -> bool:
        """Return true for files and links, including dangling symlinks."""
        return os.path.lexists(os.fspath(path))

    @classmethod
    def _path_key(cls, path: Path) -> str:
        return os.path.normcase(os.fspath(cls._absolute_path(path))).casefold()

    @classmethod
    def _companion_paths(cls, media_path: Path) -> tuple[Path, ...]:
        paths: list[Path] = []
        seen: set[str] = set()
        for builder in cls._COMPANION_BUILDERS:
            candidate = Path(builder(media_path))
            key = cls._path_key(candidate)
            if key in seen:
                continue
            seen.add(key)
            paths.append(candidate)
        return tuple(paths)

    @classmethod
    def _has_ambiguous_stem_sibling(cls, source: Path) -> bool:
        companions = {
            cls._path_key(path)
            for path in cls._companion_paths(source)
        }
        try:
            siblings = source.parent.iterdir()
        except OSError:
            return False
        source_key = cls._path_key(source)
        for sibling in siblings:
            sibling_key = cls._path_key(sibling)
            if sibling_key == source_key or sibling_key in companions:
                continue
            if (
                sibling.is_file() or sibling.is_symlink()
            ) and sibling.stem.casefold() == source.stem.casefold():
                return True
        return False

    @classmethod
    def _bundle_pairs(
        cls,
        source: Path,
        destination: Path,
        *,
        include_sidecars: bool,
    ) -> tuple[tuple[Path, Path], ...]:
        source = Path(source)
        destination = Path(destination)
        pairs: list[tuple[Path, Path]] = []
        if include_sidecars:
            existing_companions = [
                companion
                for companion in cls._companion_paths(source)
                if cls._path_exists(companion)
            ]
            if existing_companions and cls._has_ambiguous_stem_sibling(source):
                raise QuickSortAmbiguousSidecarError(
                    f"{source.name} appears to share sidecars with another same-name "
                    "media file. Rename one of the files or disable sidecar handling."
                )
            target_by_builder = {
                cls._path_key(Path(builder(source))): Path(
                    builder(destination)
                )
                for builder in cls._COMPANION_BUILDERS
            }
            for companion in existing_companions:
                key = cls._path_key(companion)
                pairs.append((companion, target_by_builder[key]))
        # Move/copy the media last so a partial companion failure can be rolled back
        # without briefly losing the primary file from its original location.
        pairs.append((source, destination))
        return tuple(pairs)

    @staticmethod
    def _remove_created_destination(destination: Path) -> None:
        if destination.is_dir() and not destination.is_symlink():
            raise QuickSortFileError(
                f"Refusing to remove unexpected destination directory: {destination}"
            )
        destination.unlink()

    @classmethod
    def _targets_are_free(cls, pairs: tuple[tuple[Path, Path], ...]) -> bool:
        return not any(cls._path_exists(target) for _source, target in pairs)

    @classmethod
    def _capture_destination_identities(
        cls,
        pairs: tuple[tuple[Path, Path], ...],
    ) -> tuple[tuple[Path, QuickSortDestinationIdentity], ...]:
        return tuple(
            (destination, QuickSortDestinationIdentity.capture(destination))
            for _source, destination in pairs
        )

    @classmethod
    def _rollback_applied_pairs(
        cls,
        pairs: tuple[tuple[Path, Path], ...],
        *,
        mode: str,
    ) -> None:
        if mode == "move":
            reverse_pairs = tuple(
                (destination, source)
                for source, destination in reversed(pairs)
            )
            cls._apply_pairs(reverse_pairs, mode="move")
            return
        if mode != "copy":
            raise QuickSortFileError(f"Unsupported file operation: {mode}")
        errors: list[str] = []
        for _source, destination in reversed(pairs):
            try:
                if cls._path_exists(destination):
                    cls._remove_created_destination(destination)
            except OSError as exc:
                errors.append(str(exc))
        if errors:
            raise QuickSortFileError("; ".join(errors))

    @classmethod
    def _capture_or_rollback(
        cls,
        pairs: tuple[tuple[Path, Path], ...],
        *,
        mode: str,
    ) -> tuple[tuple[Path, QuickSortDestinationIdentity], ...]:
        try:
            return cls._capture_destination_identities(pairs)
        except Exception as exc:
            rollback_error = ""
            try:
                cls._rollback_applied_pairs(pairs, mode=mode)
            except Exception as rollback_exc:
                rollback_error = f" Rollback also failed: {rollback_exc}"
            raise QuickSortFileError(
                f"Could not record destination identity: {exc}.{rollback_error}"
            ) from exc

    @classmethod
    def _verify_destination_identities(
        cls,
        operation: QuickSortFileOperation,
        *,
        allow_missing: bool,
    ) -> None:
        expected_by_path = {
            cls._path_key(path): identity
            for path, identity in operation.destination_identities
        }
        for _source, destination in operation.bundle_pairs:
            if not cls._path_exists(destination):
                if allow_missing:
                    continue
                raise QuickSortFileError(
                    f"Cannot undo because an output is missing: {destination}"
                )
            expected = expected_by_path.get(cls._path_key(destination))
            if expected is None:
                raise QuickSortFileError(
                    f"Cannot safely undo without destination identity: {destination}"
                )
            try:
                current = QuickSortDestinationIdentity.capture(destination)
            except OSError as exc:
                raise QuickSortFileError(
                    f"Cannot verify destination before undo: {destination}: {exc}"
                ) from exc
            if current != expected:
                raise QuickSortFileError(
                    "Cannot undo because an output was modified or replaced: "
                    f"{destination}"
                )

    @classmethod
    def _choose_destination(
        cls,
        source: Path,
        requested_destination: Path,
        *,
        include_sidecars: bool,
        collision_policy: str,
    ) -> tuple[Path, tuple[tuple[Path, Path], ...]] | None:
        destination = Path(requested_destination)
        pairs = cls._bundle_pairs(
            source,
            destination,
            include_sidecars=include_sidecars,
        )
        if cls._targets_are_free(pairs):
            return destination, pairs
        if collision_policy == "skip":
            return None
        if collision_policy != "append":
            raise QuickSortCollisionError(
                f"A file already exists in the destination bundle for {destination.name}."
            )
        counter = 1
        while counter < 100_000:
            candidate = destination.with_name(
                f"{destination.stem} ({counter}){destination.suffix}"
            )
            pairs = cls._bundle_pairs(
                source,
                candidate,
                include_sidecars=include_sidecars,
            )
            if cls._targets_are_free(pairs):
                return candidate, pairs
            counter += 1
        raise QuickSortCollisionError(
            f"Could not find an unused destination name for {destination.name}."
        )

    @classmethod
    def _apply_pairs(
        cls,
        pairs: tuple[tuple[Path, Path], ...],
        *,
        mode: str,
    ) -> None:
        completed: list[tuple[Path, Path]] = []
        active: tuple[Path, Path] | None = None
        try:
            for source, destination in pairs:
                if not cls._path_exists(source):
                    raise QuickSortFileError(f"Source file is missing: {source}")
                if cls._path_exists(destination):
                    raise QuickSortCollisionError(
                        f"Destination already exists: {destination}"
                    )
                destination.parent.mkdir(parents=True, exist_ok=True)
                active = (source, destination)
                if mode == "move":
                    shutil.move(str(source), str(destination))
                elif mode == "copy":
                    shutil.copy2(
                        str(source),
                        str(destination),
                        follow_symlinks=False,
                    )
                else:
                    raise QuickSortFileError(f"Unsupported file operation: {mode}")
                completed.append((source, destination))
                active = None
        except Exception as exc:
            rollback_errors: list[str] = []
            rollback_pairs = list(reversed(completed))
            if active is not None:
                rollback_pairs.insert(0, active)
            for source, destination in rollback_pairs:
                try:
                    destination_exists = cls._path_exists(destination)
                    source_exists = cls._path_exists(source)
                    if mode == "move" and destination_exists:
                        if not source_exists:
                            source.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(destination), str(source))
                        elif active == (source, destination):
                            # Cross-volume shutil.move may leave a partial copy at
                            # the destination while the original still exists.
                            cls._remove_created_destination(destination)
                    elif mode == "copy" and destination_exists:
                        cls._remove_created_destination(destination)
                except Exception as rollback_exc:
                    rollback_errors.append(str(rollback_exc))
            suffix = (
                f" Rollback also failed: {'; '.join(rollback_errors)}"
                if rollback_errors
                else ""
            )
            if isinstance(exc, QuickSortFileError):
                raise type(exc)(f"{exc}{suffix}") from exc
            raise QuickSortFileError(f"{exc}{suffix}") from exc

    def execute(
        self,
        *,
        source: Path,
        destination_directory: Path,
        mode: str,
        include_sidecars: bool,
        collision_policy: str,
    ) -> QuickSortFileResult:
        source = self._absolute_path(Path(source))
        if not self._path_exists(source):
            raise QuickSortFileError(f"Source file is missing: {source}")
        requested_destination = (
            self._absolute_path(Path(destination_directory)) / source.name
        )
        if requested_destination == source:
            raise QuickSortFileError(
                "The selected route points to the file's current location."
            )
        chosen = self._choose_destination(
            source,
            requested_destination,
            include_sidecars=include_sidecars,
            collision_policy=collision_policy,
        )
        if chosen is None:
            return QuickSortFileResult(
                skipped=True,
                message=f"Skipped {source.name}: destination already exists.",
            )
        destination, pairs = chosen
        self._apply_pairs(pairs, mode=mode)
        identities = self._capture_or_rollback(pairs, mode=mode)
        return QuickSortFileResult(
            operation=QuickSortFileOperation(
                mode=mode,
                source=source,
                destination=destination,
                bundle_pairs=pairs,
                destination_identities=identities,
            )
        )

    def has_requested_collision(
        self,
        *,
        source: Path,
        destination_directory: Path,
        include_sidecars: bool,
    ) -> bool:
        """Return whether the exact requested media bundle would overwrite data."""
        source = self._absolute_path(Path(source))
        requested_destination = (
            self._absolute_path(Path(destination_directory)) / source.name
        )
        pairs = self._bundle_pairs(
            source,
            requested_destination,
            include_sidecars=include_sidecars,
        )
        return not self._targets_are_free(pairs)

    def undo(self, operation: QuickSortFileOperation) -> None:
        if operation.mode == "move":
            self._verify_destination_identities(
                operation,
                allow_missing=False,
            )
            reverse_pairs = tuple(
                (destination, source)
                for source, destination in reversed(operation.bundle_pairs)
            )
            self._apply_pairs(reverse_pairs, mode="move")
            return
        if operation.mode != "copy":
            raise QuickSortFileError(
                f"Unsupported file operation: {operation.mode}"
            )
        self._verify_destination_identities(
            operation,
            allow_missing=True,
        )

        errors: list[str] = []
        for _source, destination in reversed(operation.bundle_pairs):
            try:
                if self._path_exists(destination):
                    self._remove_created_destination(destination)
            except OSError as exc:
                errors.append(str(exc))
        if errors:
            raise QuickSortFileError("; ".join(errors))

    def redo(self, operation: QuickSortFileOperation) -> None:
        self._apply_pairs(operation.bundle_pairs, mode=operation.mode)
        object.__setattr__(
            operation,
            "destination_identities",
            self._capture_or_rollback(
                operation.bundle_pairs,
                mode=operation.mode,
            ),
        )
