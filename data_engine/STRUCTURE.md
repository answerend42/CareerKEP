# data_engine 目录结构

完整流水线说明见 [`PIPELINE.md`](PIPELINE.md)。

```
data_engine/
├── PIPELINE.md              # 分步流水线（推荐先读）
├── cli.py                   # 全部子命令入口
├── config.json / config.py  # Step 0 配置
│
├── corpus/                  # Step 1 语料抓取
│   ├── pipeline.py          # run() 编排
│   ├── targets.py
│   ├── http_client.py
│   ├── cache.py
│   ├── doc_id.py
│   ├── normalizer.py
│   ├── doc_writer.py
│   ├── struct_writer.py
│   ├── reporting.py
│   └── sources/             # wiki / github / roadmap / onet
│
├── proposers/               # Step 3 候选生成
│   ├── aliases.py
│   ├── edges_cooccurrence.py
│   ├── edges_roadmap.py
│   ├── nodes.py
│   ├── discovery.py
│   ├── discovery_filters.py
│   └── nodes_auto/
│
├── proposals/               # Step 3 中间 JSON
│   └── store.py
│
├── graph/                   # Step 4–5 写 seeds / 审核 / viz
│   ├── applier.py
│   ├── packages.py
│   ├── review.py
│   └── viz.py
│
├── core/                    # 共享：paths、NodePackage
├── scripts/                 # curated 批量（v5_balanced_batch.py）
├── tests/
│
├── 【兼容 shim】            # 旧 import；新代码用子包路径
│   pipeline.py, targets.py, doc_writer.py, …
│   sources/__init__.py
│   applier.py, review.py, viz.py, proposals_io.py
│
└── output/                  # proposals/、graph_view.html、run_report.json
```

## 兼容层

| 旧路径 | 新路径 |
| --- | --- |
| `data_engine.pipeline` | `data_engine.corpus.pipeline` |
| `data_engine.doc_writer` | `data_engine.corpus.doc_writer` |
| `data_engine.sources` | `data_engine.corpus.sources` |
| `data_engine.applier` | `data_engine.graph.applier` |
| `data_engine.proposals_io` | `data_engine.proposals.store` |
