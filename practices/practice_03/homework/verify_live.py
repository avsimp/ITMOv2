"""Живые MCP-вызовы через stdio и проверка PDF. Результаты в новом output/run-* ."""

import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

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
            assert result["result_file"] == result["pdf"] == str(pdf_path)
            assert result["archive"] is None and result["attachments"] == []
            assert not pdf_path.with_suffix(".zip").exists()
            assert not pdf_path.with_suffix(".files").exists()
            await call("create_pdf", {"topic_ids": [9048], "output_path": str(pdf_path)}, error=True)
            attached = await call("create_pdf", {"topic_ids": [9111], "output_path": str(output / "таблица.pdf")})
            assert attached["attachments"] == ["1.ods"]
            archive_path = output / "таблица.zip"
            assert attached["result_file"] == attached["archive"] == str(archive_path)
            attachment = output / "таблица.files" / attached["attachments"][0]
            assert attachment.read_bytes().startswith(b"PK"), "ODS должен быть ZIP-контейнером"
            with ZipFile(archive_path) as archive:
                assert archive.namelist() == ["таблица.pdf", "таблица.files/1.ods"]
                assert archive.read("таблица.pdf") == Path(attached["pdf"]).read_bytes()
                assert archive.read("таблица.files/1.ods") == attachment.read_bytes()
                extracted = output / "распаковано"
                archive.extractall(extracted)
            with pymupdf.open(extracted / "таблица.pdf") as pdf:
                links = [link for page in pdf for link in page.get_links()]
                assert links and {unquote(link["file"]) for link in links} == {"таблица.files/1.ods"}
                assert all(not Path(unquote(link["file"])).is_absolute() and "uri" not in link for link in links)
                assert "1.ods" in "".join(page.get_text() for page in pdf)
                for link in links:
                    assert (extracted / unquote(link["file"])).read_bytes() == attachment.read_bytes()
                for index, page in enumerate(pdf):
                    page.get_pixmap(matrix=pymupdf.Matrix(1.2, 1.2)).save(output / f"attachment-page-{index + 1}.png")
            before = archive_path.read_bytes()
            await call("create_pdf", {"topic_ids": [9111], "output_path": attached["pdf"]}, error=True)
            assert archive_path.read_bytes() == before
            conflict = output / "конфликт.zip"
            conflict.write_bytes(b"existing ZIP placeholder")
            await call("create_pdf", {"topic_ids": [9080], "output_path": str(conflict.with_suffix(".pdf"))}, error=True)
            assert conflict.read_bytes() == b"existing ZIP placeholder"
            assert not conflict.with_suffix(".pdf").exists()
            print(f"ZIP: {archive_path}, состав и ссылки после распаковки проверены")
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
