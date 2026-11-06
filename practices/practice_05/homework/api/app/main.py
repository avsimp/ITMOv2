"""Local same-origin HTTP API. Shared YAML is the only editable OpenAPI contract."""
import copy
import logging
import re
from pathlib import Path
from typing import Literal
from uuid import UUID

import anyio
import yaml
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import TypeAdapter, ValidationError
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

from app.bank_adapter import Bank, BankAdapter
from app.config import Settings
from app.errors import ApiError, invalid
from app.schemas import CreateWork, HttpUrl
from app.storage import Storage
from app.works import WorkService

logger = logging.getLogger("homework.api")


def query(request, allowed, arrays=()):
    result = {}
    for key, value in request.query_params.multi_items():
        if key not in allowed:
            raise invalid("query", "Неизвестный параметр запроса")
        if key in result and key not in arrays:
            raise invalid(key, "Параметр указан несколько раз")
        if key in arrays:
            result.setdefault(key, []).append(value)
        else:
            result[key] = value
    return result


def integer(value, field, low=1, high=None):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+", value):
        raise invalid(field, "Требуется целое число")
    try:
        result = int(value)
    except ValueError as exc:
        raise invalid(field, "Требуется целое число") from exc
    if result < low or (high is not None and result > high):
        raise invalid(field, "Значение вне допустимого диапазона")
    return result


def validation_problem(exc):
    fields = []
    for item in exc.errors():
        location = [str(v) for v in item["loc"] if v not in {"body", "query", "path"}]
        name = ".".join(location)
        if not re.fullmatch(r"[\w.]+", name):
            name = "body"
        fields.append({"field": name or "body", "message": "Недопустимое или отсутствующее значение"})
    return ApiError(422, "validation_error", "Проверьте параметры запроса", fields)


class UIAssets(StaticFiles):
    async def check_config(self):
        if not Path(self.directory).is_dir():
            raise HTTPException(404)
        await super().check_config()


def create_app(settings=None, *, bank_factory=None, exporter=None):
    application = FastAPI(redirect_slashes=False)
    application.state.settings = settings or Settings()
    config = application.state.settings
    factory = bank_factory or Bank
    service = WorkService(config, factory, exporter)
    storage = service.storage
    application.state.work_service = service

    @application.exception_handler(ApiError)
    async def app_error(request, exc):
        return JSONResponse(exc.payload, status_code=exc.status)

    @application.exception_handler(HTTPException)
    async def http_error(request, exc):
        code = "not_found" if exc.status_code == 404 else "invalid_request"
        return JSONResponse({"error": {"code": code, "message": "Запрошенный ресурс недоступен", "fields": []}},
                            status_code=exc.status_code, headers=exc.headers)

    @application.exception_handler(RequestValidationError)
    async def request_error(request, exc):
        problem = validation_problem(exc)
        return JSONResponse(problem.payload, status_code=problem.status)

    @application.exception_handler(Exception)
    async def unexpected(request, exc):
        logger.exception("request failed")
        return JSONResponse({"error": {"code": "internal_error", "message": "Не удалось выполнить операцию",
                                       "fields": []}}, status_code=500)

    def adapter():
        return BankAdapter(factory(), config)

    @application.get("/api/v1/categories")
    async def categories(request: Request):
        params = query(request, {"ege_number"})
        number = integer(params.get("ege_number"), "ege_number", high=27)
        return await anyio.to_thread.run_sync(lambda: adapter().categories(number))

    @application.get("/api/v1/tasks")
    async def search(request: Request):
        params = query(request, {"ege_number", "category_ids", "exclude_ids", "contains", "offset", "limit"},
                       {"category_ids", "exclude_ids"})
        number = integer(params.get("ege_number"), "ege_number", high=27)
        cats = [integer(v, "category_ids") for v in params["category_ids"]] if "category_ids" in params else None
        excluded = [integer(v, "exclude_ids") for v in params.get("exclude_ids", [])]
        offset = integer(params.get("offset", "0"), "offset", low=0)
        limit = integer(params.get("limit", "10"), "limit", high=30)
        return await anyio.to_thread.run_sync(lambda: adapter().search(
            number, cats, params.get("contains", ""), excluded, offset, limit))

    @application.get("/api/v1/tasks/{topic_id}/resources/{kind}")
    async def resource(request: Request, topic_id: str, kind: Literal["image", "attachment"]):
        ident = integer(topic_id, "topic_id")
        params = query(request, {"url"})
        try:
            url = TypeAdapter(HttpUrl).validate_python(params.get("url"))
        except (ValueError, ValidationError) as exc:
            raise invalid("url", "Требуется HTTP(S)-адрес ресурса") from exc
        data, mime, headers = await anyio.to_thread.run_sync(lambda: adapter().resource(ident, kind, url))
        return Response(data, media_type=mime, headers=headers)

    @application.post("/api/v1/works", status_code=201)
    async def create(request: Request):
        query(request, set())
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            raise ApiError(415, "invalid_request", "Требуется application/json")
        try:
            body = await request.json()
        except (ValueError, UnicodeError) as exc:
            raise ApiError(400, "invalid_request", "Некорректный JSON запроса") from exc
        try:
            parsed = CreateWork.model_validate(body)
        except ValidationError as exc:
            raise validation_problem(exc) from exc
        work = await service.create(parsed)
        return JSONResponse(work.model_dump(mode="json"), status_code=201,
                            headers={"Location": config.url(f"/api/v1/works/{work.work_id}")})

    @application.get("/api/v1/works/{work_id}")
    async def metadata(request: Request, work_id: UUID):
        query(request, set())
        return await anyio.to_thread.run_sync(lambda: storage.public(storage.read(str(work_id))).model_dump())

    @application.get("/api/v1/works/{work_id}/files/{kind}")
    async def material(request: Request, work_id: UUID, kind: Literal["result", "pdf", "archive", "answers", "sources"]):
        query(request, set())
        path, mime, disposition, info = await anyio.to_thread.run_sync(lambda: storage.material(str(work_id), kind))
        return FileResponse(path, media_type=mime, filename=path.name, stat_result=info,
                            content_disposition_type=disposition,
                            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @application.get("/", include_in_schema=False)
    async def index():
        path = config.ui_root / "index.html"
        info = Storage.regular(path)
        return FileResponse(path, media_type="text/html", stat_result=info)

    application.mount("/assets", UIAssets(directory=config.ui_root / "assets", check_dir=False), name="assets")

    def openapi():
        contract_path = Path(__file__).resolve().parents[2] / "contracts/api-v1.yaml"
        value = yaml.safe_load(contract_path.read_text())
        value["servers"] = [{"url": config.origin, "description": "Настроенный локальный origin"}]
        return copy.deepcopy(value)

    application.openapi = openapi

    return application


app = create_app()
