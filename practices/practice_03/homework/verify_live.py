"""Живые MCP-вызовы через stdio и проверка PDF. Результаты в новом output/run-* ."""

import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pymupdf
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent


async def main():
    output = ROOT / "output" / datetime.now().strftime("run-%Y%m%d-%H%M%S-%f")
    output.mkdir(parents=True)
    records = []
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "server.py")])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {t.name for t in tools.tools} == {"list_categories", "search_tasks", "get_task", "create_pdf"}

            async def call(name, arguments, error=False):
                result = await session.call_tool(name, arguments)
                records.append({"tool": name, "arguments": arguments, "result": result.model_dump(mode="json")})
                (output / "mcp-calls.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
                assert bool(result.isError) == error, result
                if result.isError:
                    return None
                return result.structuredContent or json.loads(result.content[0].text)

            for number in (1, 5, 19):
                await call("list_categories", {"ege_number": number})
            for number, categories in ((1, [12, 13]), (5, [27, 28, 144]), (19, [163])):
                found = await call("search_tasks", {"ege_number": number, "category_ids": categories, "limit": 2})
                print(f"КИМ {number}: найдено {found['total']}")
            task = await call("get_task", {"topic_id": 9080})
            assert task["answer"] == "8"
            await call("get_task", {"topic_id": 999999999}, error=True)
            await call("search_tasks", {"ege_number": 5, "category_ids": [163]}, error=True)
            pdf_path = output / "подборка.pdf"
            result = await call("create_pdf", {"topic_ids": [9048, 9080, 9175], "output_path": str(pdf_path)})
            assert result["answers"] == "1. 13\n2. 8\n3. 19) 41; 20) 36 40; 21) 35"
            await call("create_pdf", {"topic_ids": [9048], "output_path": str(pdf_path)}, error=True)
            attached = await call("create_pdf", {"topic_ids": [9111], "output_path": str(output / "таблица.pdf")})
            assert len(attached["attachments"]) == 1
            attachment = output / "таблица.files" / attached["attachments"][0]
            assert attachment.read_bytes().startswith(b"PK"), "ODS должен быть ZIP-контейнером"
    with pymupdf.open(pdf_path) as pdf:
        text = "\n".join(p.get_text() for p in pdf)
        assert all(re.search(rf"\b{n}\)", text) for n in (1, 2, 3))
        assert "Показать ответ" not in text and "Задача №" not in text
        assert "Вопрос 3." in text and "На вход алгоритма" in text
        assert sum(len(p.get_images()) for p in pdf) >= 1
        for index, page in enumerate(pdf):
            page.get_pixmap(matrix=pymupdf.Matrix(1.2, 1.2)).save(output / f"page-{index + 1}.png")
        print(f"PDF: {len(pdf)} страниц, кириллица и изображение присутствуют")
    print(output)


if __name__ == "__main__":
    asyncio.run(main())
