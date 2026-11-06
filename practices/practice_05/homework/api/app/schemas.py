"""HTTP projection models. The shared YAML remains the normative contract."""
import re
import unicodedata
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator


def http_url(value):
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc or not parts.hostname:
        raise ValueError("HTTP(S) URL required")
    _ = parts.port
    return value


PositiveId = Annotated[StrictInt, Field(gt=0)]
HttpUrl = Annotated[str, AfterValidator(http_url)]
Nonempty = Annotated[str, Field(min_length=1)]
TopicIds = Annotated[list[PositiveId], Field(min_length=1, max_length=100)]
MediaType = Literal["application/pdf", "application/zip", "text/plain; charset=utf-8", "application/json"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Category(Model):
    id: PositiveId
    title: Nonempty


class CategoryResult(Model):
    requested_ege_number: Annotated[StrictInt, Field(ge=1, le=27)]
    ege_number: Annotated[StrictInt, Field(ge=1, le=27)]
    categories: Annotated[list[Category], Field(min_length=1)]


class Task(Model):
    id: PositiveId
    ege_numbers: list[PositiveId]
    statement: Nonempty
    statement_html: Nonempty
    source_url: HttpUrl
    listing_url: HttpUrl
    images: list[HttpUrl]
    attachments: list[HttpUrl]

    @field_validator("ege_numbers")
    @classmethod
    def numbers(cls, value):
        if value != [19, 20, 21] and not (len(value) == 1 and value[0] in set(range(1, 28)) - {19, 20, 21}):
            raise ValueError("Expected a single ordinary number or the complete 19-21 block")
        return value


class SearchResult(Model):
    requested_ege_number: Annotated[StrictInt, Field(ge=1, le=27)]
    ege_number: Annotated[StrictInt, Field(ge=1, le=27)]
    total: Annotated[StrictInt, Field(ge=0)]
    offset: Annotated[StrictInt, Field(ge=0)]
    limit: Annotated[StrictInt, Field(ge=1, le=30)]
    next_offset: Annotated[StrictInt, Field(ge=0)] | None
    source_url: HttpUrl
    tasks: Annotated[list[Task], Field(max_length=30)]


class CreateWork(Model):
    topic_ids: TopicIds
    name: str | None = None

    @field_validator("topic_ids")
    @classmethod
    def unique_ids(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("IDs must be unique")
        return value

    @field_validator("name", mode="before")
    @classmethod
    def name_rules(cls, value):
        if not isinstance(value, str):
            raise ValueError("Explicit name must be a string")
        if any(unicodedata.category(char) == "Cc" for char in value):
            raise ValueError("Control characters in name")
        value = value.strip()
        if not 1 <= len(value) <= 80 or any(c in value for c in "/\\") or value in {".", ".."} or re.match(r"^[A-Za-z]:", value):
            raise ValueError("Invalid name")
        return value


class Artifact(Model):
    url: HttpUrl
    filename: Nonempty
    media_type: MediaType
    audience: Literal["student", "preview", "teacher"]


class WorkBase(Model):
    work_id: str
    name: Annotated[str, Field(min_length=1, max_length=80)]
    created_at: str
    topic_ids: TopicIds
    count: Annotated[StrictInt, Field(ge=1, le=100)]
    attachments: list[Nonempty]

    @field_validator("work_id")
    @classmethod
    def uuid4(cls, value):
        ident = UUID(value)
        if ident.version != 4 or str(ident) != value:
            raise ValueError("Expected canonical UUIDv4")
        return value

    @field_validator("created_at")
    @classmethod
    def timestamp(cls, value):
        if datetime.fromisoformat(value).tzinfo is None:
            raise ValueError("Expected timezone-aware datetime")
        return value

    @field_validator("attachments")
    @classmethod
    def basenames(cls, value):
        if any(name in {".", ".."} or any(c in name for c in "/\\\x00") for name in value):
            raise ValueError("Invalid attachment filename")
        return value

    @model_validator(mode="after")
    def count_and_order(self):
        if self.count != len(self.topic_ids) or len(set(self.topic_ids)) != self.count:
            raise ValueError("Count/IDs mismatch")
        return self


class Work(WorkBase):
    result: Artifact
    pdf: Artifact
    archive: Artifact | None
    answers: Artifact
    sources: Artifact


class WorkRecord(WorkBase):
    schema_version: Literal[1]
    has_archive: StrictBool
    files: dict[str, str]
