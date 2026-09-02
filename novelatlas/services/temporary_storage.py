"""Task-scoped temporary storage for uploaded novel text."""

import json
import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from novelatlas.schemas.document import UploadedDocument
from novelatlas.services.text_decoder import DecodedText


class UploadNotFoundError(FileNotFoundError):
    """Raised when a temporary upload does not exist or has expired."""


class TemporaryUploadStorage:
    """Store normalized source text until a task is deleted or expires."""

    def __init__(self, *, ttl_seconds: int, root: Path | None = None) -> None:
        self.ttl = timedelta(seconds=ttl_seconds)
        self._owns_root = root is None
        self.root = (
            Path(tempfile.mkdtemp(prefix="novelatlas-uploads-"))
            if root is None
            else root
        )
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)

    def begin_upload(self) -> tuple[str, Path]:
        """Create an isolated task directory and return its raw upload path."""

        task_id = uuid4().hex
        task_directory = self.root / task_id
        task_directory.mkdir(mode=0o700)
        return task_id, task_directory / "upload.raw"

    def finalize_upload(
        self,
        *,
        task_id: str,
        filename: str,
        size_bytes: int,
        decoded: DecodedText,
    ) -> UploadedDocument:
        """Replace raw bytes with normalized UTF-8 text and metadata."""

        task_directory = self._task_directory(task_id)
        raw_path = task_directory / "upload.raw"
        if not raw_path.is_file():
            raise UploadNotFoundError(task_id)

        created_at = datetime.now(UTC)
        metadata = UploadedDocument(
            task_id=task_id,
            filename=filename,
            detected_encoding=decoded.encoding,
            size_bytes=size_bytes,
            character_count=len(decoded.content),
            created_at=created_at,
            expires_at=created_at + self.ttl,
        )

        (task_directory / "source.txt").write_text(
            decoded.content,
            encoding="utf-8",
            newline="\n",
        )
        (task_directory / "metadata.json").write_text(
            metadata.model_dump_json(indent=2),
            encoding="utf-8",
        )
        raw_path.unlink(missing_ok=True)
        return metadata

    def get(self, task_id: str) -> UploadedDocument:
        """Return metadata for an unexpired temporary upload."""

        metadata_path = self._task_directory(task_id) / "metadata.json"
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata = UploadedDocument.model_validate(payload)
        except (FileNotFoundError, json.JSONDecodeError, ValueError) as error:
            raise UploadNotFoundError(task_id) from error

        if metadata.expires_at <= datetime.now(UTC):
            self.delete(task_id)
            raise UploadNotFoundError(task_id)
        return metadata

    def source_path(self, task_id: str) -> Path:
        """Return the normalized UTF-8 source path for later processing."""

        self.get(task_id)
        return self._task_directory(task_id) / "source.txt"

    def delete(self, task_id: str) -> bool:
        """Delete a task directory and all temporary contents."""

        task_directory = self._task_directory(task_id)
        if not task_directory.is_dir():
            return False
        shutil.rmtree(task_directory)
        return True

    def cleanup_expired(self, *, now: datetime | None = None) -> int:
        """Delete expired, abandoned, or invalid task directories."""

        comparison_time = now or datetime.now(UTC)
        deleted = 0
        for task_directory in self.root.iterdir():
            if not task_directory.is_dir():
                continue

            metadata_path = task_directory / "metadata.json"
            should_delete = False
            try:
                metadata = UploadedDocument.model_validate_json(
                    metadata_path.read_text(encoding="utf-8")
                )
                should_delete = metadata.expires_at <= comparison_time
            except (FileNotFoundError, ValueError):
                modified_at = datetime.fromtimestamp(
                    task_directory.stat().st_mtime,
                    tz=UTC,
                )
                should_delete = modified_at + self.ttl <= comparison_time

            if should_delete:
                shutil.rmtree(task_directory)
                deleted += 1
        return deleted

    def discard_incomplete(self, task_id: str) -> None:
        """Remove an upload that failed validation or decoding."""

        self.delete(task_id)

    def close(self) -> None:
        """Remove the process-owned temporary root during shutdown."""

        if self._owns_root:
            shutil.rmtree(self.root, ignore_errors=True)

    def _task_directory(self, task_id: str) -> Path:
        if len(task_id) != 32 or any(character not in "0123456789abcdef" for character in task_id):
            raise UploadNotFoundError(task_id)
        return self.root / task_id
