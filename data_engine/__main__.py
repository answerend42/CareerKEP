"""让 `python3 -m data_engine` 直接进入 CLI。"""

from __future__ import annotations

from .cli import main


if __name__ == "__main__":
    raise SystemExit(main())
