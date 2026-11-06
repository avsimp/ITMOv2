"""An export stays inside the original long request, including readiness publication."""
import logging
from datetime import datetime, timezone

import anyio

from app.bank_adapter import Bank, BankAdapter, export_pdf
from app.errors import ApiError
from app.schemas import WorkRecord
from app.storage import Storage

logger = logging.getLogger("homework.api")


class WorkService:
    def __init__(self, settings, bank_factory=None, exporter=None):
        self.settings = settings
        self.storage = Storage(settings)
        self.bank_factory = bank_factory or Bank
        self.exporter = exporter or export_pdf
        self.limiter = anyio.CapacityLimiter(1)

    def _create(self, request):
        ident = None
        try:
            ident, folder = self.storage.allocate()
            logger.info("export started work_id=%s", ident)
            now = datetime.now(timezone.utc)
            bank = BankAdapter(self.bank_factory(), self.settings)
            result = self.exporter(bank, request.topic_ids, str(folder / "work.pdf"))
            attachments = result["attachments"]
            has_archive = bool(attachments)
            if result["count"] != len(request.topic_ids) or bool(result["archive"]) != has_archive:
                raise ValueError("Incomplete exporter result")
            record = WorkRecord(work_id=ident, name=request.name or now.strftime("Работа %Y-%m-%d %H:%M:%S"),
                                created_at=now.isoformat(), topic_ids=request.topic_ids, count=result["count"],
                                attachments=attachments, schema_version=1, has_archive=has_archive,
                                files=self.storage.files(has_archive))
            public = self.storage.public(record)
            self.storage.publish(folder, record)
            logger.info("export ready work_id=%s", ident)
            return public
        except ApiError:
            logger.warning("export failed work_id=%s", ident)
            raise
        except Exception as exc:
            from render import OutputConflictError
            if isinstance(exc, (OutputConflictError, FileExistsError)):
                raise ApiError(409, "output_conflict", "Выходные материалы уже существуют") from exc
            logger.exception("export failed work_id=%s", ident)
            raise ApiError(500, "export_failed", "Не удалось подготовить все материалы работы") from exc

    async def create(self, request):
        async with self.limiter:
            return await anyio.to_thread.run_sync(self._create, request, abandon_on_cancel=False)
