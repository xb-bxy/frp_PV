"""配置管理器 — 线程安全读写 config.json"""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock


class ConfigManager:
    """统一读写 config.json, 线程安全"""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = Lock()
        self._data: dict = {}
        self.reload()

    # ── 读写 ──

    def reload(self) -> None:
        with open(self._path, "r", encoding="utf-8") as f:
            self._data = json.load(f)

    def save(self) -> None:
        with self._lock:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)

    # ── 字段操作 ──

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        self._data[key] = value

    @property
    def raw(self) -> dict:
        """直接暴露底层 dict (供 Jinja 模板访问)"""
        return self._data
