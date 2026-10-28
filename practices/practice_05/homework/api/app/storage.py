"""Private per-export directories; work.json is the final readiness marker."""
import json
import os
import stat
from uuid import UUID, uuid4

from pydantic import ValidationError

from app.errors import ApiError, missing
from app.schemas import Artifact, Work, WorkRecord

FILES = {"pdf": "work.pdf", "answers": "work.answers.txt", "sources": "work.sources.json"}
MIMES = {"pdf": "application/pdf", "archive": "application/zip", "answers": "text/plain; charset=utf-8",
         "sources": "application/json"}


def conflict():
    return ApiError(409, "output_conflict", "Выходные материалы уже существуют")


class Storage:
    def __init__(self, settings):
        self.settings = settings
        self.root = settings.storage_root

    @staticmethod
    def files(has_archive):
        return dict(FILES, **({"archive": "work.zip"} if has_archive else {}))

    def allocate(self):
        if self.root.is_symlink():
            raise OSError("Invalid storage root")
        self.root.mkdir(parents=True, exist_ok=True)
        ident = str(uuid4())
        folder = self.root / ident
        try:
            folder.mkdir()
        except FileExistsError as exc:
            raise conflict() from exc
        return ident, folder

    def folder(self, ident):
        try:
            if str(UUID(ident)) != ident:
                raise ValueError("Noncanonical ID")
        except (ValueError, TypeError, AttributeError) as exc:
            raise missing() from exc
        if self.root.is_symlink():
            raise missing()
        folder = self.root / ident
        if folder.is_symlink() or not folder.is_dir():
            raise missing()
        return folder

    @staticmethod
    def regular(path):
        try:
            info = path.lstat()
        except FileNotFoundError as exc:
            raise missing() from exc
        if not stat.S_ISREG(info.st_mode):
            raise missing()
        return info

    def publish(self, folder, record):
        if folder.is_symlink() or folder.parent != self.root:
            raise OSError("Invalid work directory")
        try:
            for name in record.files.values():
                self.regular(folder / name)
            if record.has_archive:
                assets = folder / "work.files"
                if assets.is_symlink() or not assets.is_dir():
                    raise OSError("Missing assets")
                for name in record.attachments:
                    self.regular(assets / name)
        except ApiError as exc:
            raise OSError("Incomplete export") from exc
        temporary, marker = folder / "work.json.tmp", folder / "work.json"
        try:
            with temporary.open("xb") as output:
                output.write(record.model_dump_json().encode("utf-8"))
                output.flush()
                os.fsync(output.fileno())
            # Atomic exclusive publication: unlike replace(), never overwrites a marker.
            os.link(temporary, marker)
            temporary.unlink()
        except FileExistsError as exc:
            raise conflict() from exc

    def read(self, ident):
        folder = self.folder(ident)
        marker = folder / "work.json"
        self.regular(marker)
        try:
            descriptor = os.open(marker, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(descriptor, encoding="utf-8") as source:
                record = WorkRecord.model_validate(json.load(source))
            if record.work_id != ident or record.files != self.files(record.has_archive):
                raise ValueError("Invalid work record")
            if record.has_archive != bool(record.attachments):
                raise ValueError("Invalid archive metadata")
            return record
        except FileNotFoundError as exc:
            raise missing() from exc
        except (OSError, ValueError, ValidationError) as exc:
            raise ApiError(500, "internal_error", "Не удалось прочитать метаданные работы") from exc

    def public(self, record):
        def artifact(kind, target, audience):
            return Artifact(url=self.settings.url(f"/api/v1/works/{record.work_id}/files/{kind}"),
                            filename=record.files[target], media_type=MIMES[target], audience=audience)

        target = "archive" if record.has_archive else "pdf"
        values = record.model_dump(exclude={"schema_version", "has_archive", "files"})
        return Work(**values, result=artifact("result", target, "student"), pdf=artifact("pdf", "pdf", "preview"),
                    archive=artifact("archive", "archive", "student") if record.has_archive else None,
                    answers=artifact("answers", "answers", "teacher"), sources=artifact("sources", "sources", "teacher"))

    def material(self, ident, kind):
        record = self.read(ident)
        target = ("archive" if record.has_archive else "pdf") if kind == "result" else kind
        if target not in record.files:
            raise missing()
        path = self.folder(ident) / record.files[target]
        info = self.regular(path)
        return path, MIMES[target], "inline" if kind == "pdf" else "attachment", info
