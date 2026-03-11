"""数据模型 — 通用数据结构与记录类"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional


class RingLog:
    """固定容量的环形日志缓存 (GIL 保证原子性, 无需加锁)"""

    def __init__(self, maxlen: int = 500) -> None:
        self._maxlen = maxlen
        self._buf: list = []

    def append(self, item) -> None:
        self._buf.append(item)
        if len(self._buf) > self._maxlen:
            del self._buf[: len(self._buf) - self._maxlen]

    @property
    def snapshot(self) -> list:
        return list(self._buf)

    def __len__(self) -> int:
        return len(self._buf)


@dataclass
class ConnectionRecord:
    """单条访问聚合记录 (ip + module 唯一)"""

    ip: str
    module: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    country: str = ""
    desc: str = ""
    time: str = ""
    count: int = 1

    def to_dict(self) -> dict:
        return asdict(self)
