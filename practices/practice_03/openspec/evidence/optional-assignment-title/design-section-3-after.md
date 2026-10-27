### 3. Одна версия PDF для отдельного файла и ZIP

Существующий поток уже записывает одни и те же финальные байты PDF на диск и в ZIP. Заголовок формируется до печати; шаги обработки приложений и PDF-ссылок продолжают работать по прежнему плану. `pdf_sha256` автоматически относится к итоговому PDF с заголовком.

```mermaid
sequenceDiagram
    participant Export as export_pdf
    participant Browser as Chromium
    participant LinkFix as PDF link normalization
    participant File as PDF file
    participant Archive as ZIP archive
    Export->>Browser: HTML with optional title and tasks
    Browser-->>Export: PDF bytes
    opt Attachments present
        Export->>LinkFix: PDF bytes and link map
        LinkFix-->>Export: Final PDF bytes
    end
    Note over Export: Compute pdf_sha256 from final PDF bytes
    Export->>File: Write final PDF bytes
    opt Attachments present
        Export->>Archive: Same final PDF bytes and attachments
    end
```

Не добавлять заголовок в `tasks`, ответы, `attachment_map` или поля ответа. Он не меняет количество задач, их номера, имена приложений и выбор `result_file`.
