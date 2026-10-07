"""MCP-сервер polyakov. Запуск: python server.py (stdio)."""

import asyncio

from mcp.server.fastmcp import FastMCP

from polyakov import Bank
from render import export_pdf

mcp = FastMCP("polyakov")
bank = Bank()


@mcp.tool()
def list_categories(ege_number: int) -> dict:
    """Категории Полякова по номеру КИМ. 19, 20, 21 возвращают категории общей тройки."""
    return {"categories": bank.categories(ege_number)}


@mcp.tool()
def search_tasks(ege_number: int, category_ids: list[int] | None = None,
                 contains: str = "", exclude_ids: list[int] | None = None,
                 offset: int = 0, limit: int = 10) -> dict:
    """Оригинальные условия и ответы с сайта. contains — подстрока, не оценка сложности.

    Категории сначала получите через list_categories. None — все категории.
    Одна запись 19–21 содержит общую игру и три вопроса. limit от 1 до 30.
    Сложность и соответствие подтипу оценивает агент по полным условиям.
    """
    return bank.search(ege_number, category_ids, contains, exclude_ids, offset, limit)


@mcp.tool()
def get_task(topic_id: int) -> dict:
    """Получить задачу по ID базы генератора: условие, ответ, изображения, приложения."""
    return bank.get(topic_id)


@mcp.tool()
async def create_pdf(topic_ids: list[int], output_path: str) -> dict:
    """Создать PDF по ID в заданном порядке. Принимает только ID, не придуманные условия.

    Абсолютный путь .pdf. Только 1), 2), условия и рисунки, без заголовков и ответов.
    Ответы и источники сохраняются отдельно. Существующие файлы не перезаписываются.
    """
    return await asyncio.to_thread(export_pdf, bank, topic_ids, output_path)


if __name__ == "__main__":
    mcp.run(transport="stdio")
