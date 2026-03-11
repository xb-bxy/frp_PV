"""自动扫描并导入本目录下所有 provider 模块, 触发装饰器注册."""

from importlib import import_module
from pathlib import Path

_dir = Path(__file__).parent
for _f in sorted(_dir.glob("*.py")):
    if not _f.name.startswith("_"):
        import_module(f"{__package__}.{_f.stem}")
