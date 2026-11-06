"""Stable application errors; dependency messages never reach the browser."""


class ApiError(Exception):
    def __init__(self, status, code, message, fields=None):
        super().__init__(message)
        self.status = status
        self.payload = {"error": {"code": code, "message": message, "fields": fields or []}}


def invalid(field, message="Недопустимое значение"):
    return ApiError(422, "validation_error", "Проверьте параметры запроса", [{"field": field, "message": message}])


def missing():
    return ApiError(404, "not_found", "Материал или работа отсутствует либо удалена")
