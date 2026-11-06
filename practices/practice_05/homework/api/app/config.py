"""Server-owned locations and origin; independent of the launch directory."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

API_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = API_ROOT.parents[2] / "practice_03/homework"


@dataclass(frozen=True)
class Settings:
    origin: str = field(default_factory=lambda: os.getenv("HOMEWORK_API_ORIGIN", "http://127.0.0.1:8000"))
    storage_root: Path = field(default_factory=lambda: Path(os.getenv("HOMEWORK_STORAGE_ROOT", API_ROOT / "var/works")))
    ui_root: Path = field(default_factory=lambda: Path(os.getenv("HOMEWORK_UI_ROOT", API_ROOT.parent / "ui")))

    def __post_init__(self):
        parts = urlsplit(self.origin)
        if (parts.scheme not in {"http", "https"} or parts.hostname != "127.0.0.1"
                or parts.username or parts.password or parts.path not in {"", "/"} or parts.query or parts.fragment):
            raise ValueError("HOMEWORK_API_ORIGIN must be a loopback HTTP(S) origin")
        _ = parts.port
        object.__setattr__(self, "origin", self.origin.rstrip("/"))
        for key in ("storage_root", "ui_root"):
            path = Path(getattr(self, key)).expanduser()
            object.__setattr__(self, key, path if path.is_absolute() else API_ROOT / path)

    def url(self, path):
        return self.origin + path
