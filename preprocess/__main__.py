"""让 `python3 -m preprocess` 可以直接运行预处理流水线。"""

from __future__ import annotations

from .pipeline import main


if __name__ == "__main__":
    # 这里不额外包一层逻辑，直接复用 pipeline 的命令行入口，避免两套参数解析分叉。
    main()
