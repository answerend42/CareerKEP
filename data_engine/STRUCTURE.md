# data_engine 目录结构

```
data_engine/
├── __main__.py          # python -m data_engine
├── cli.py               # 子命令入口
├── config.json
├── config.py
│
├── core/                # 共享类型与路径
│   ├── paths.py         # SEED_*、PROPOSALS_DIR、WEB_GH_ROOT
│   └── package.py       # NodePackage（node+edges+aliases 原子单元）
│
├── corpus/              # （语料抓取，根目录模块，历史布局）
│   pipeline.py, targets.py, http_client.py, sources/, ...
│
├── proposals/           # 提案中间存储
│   └── store.py         # proposals/*.json、node_packages.json
│
├── proposers/           # 扩图候选生成
│   ├── discovery.py     # 从 web/gh 挖新 token（nodes + nodes_auto 共用）
│   ├── nodes.py         # 仅 node 候选 → review
│   ├── nodes_auto/      # 半自动 evidence 节点包
│   │   ├── corpus_index.py   # 单次扫描 gh，token→父实体共现
│   │   ├── parent_attach.py
│   │   ├── rules.py
│   │   ├── builder.py
│   │   └── proposer.py
│   ├── aliases.py, edges_*.py
│   └── candidate.py
│
├── graph/               # 图谱写入与可视化
│   ├── applier.py       # apply_* / apply_batch / rollback
│   ├── packages.py      # apply_node_packages
│   ├── review.py        # review / apply_auto
│   └── viz.py
│
├── scripts/             # 一次性 curated batch（如 v5_balanced_batch.py）
├── tests/
└── output/              # proposals/、graph_view.html、run_report.json
```

## 兼容层（根目录薄封装）

旧 import 仍可用，新代码请用子包路径：

| 旧路径 | 新路径 |
| --- | --- |
| `data_engine.applier` | `data_engine.graph.applier` |
| `data_engine.review` | `data_engine.graph.review` |
| `data_engine.viz` | `data_engine.graph.viz` |
| `data_engine.proposals_io` | `data_engine.proposals.store` |

## 半自动加节点工作流

```bash
# config.json → proposers.nodes_auto.enabled = true
python3 -m data_engine propose --proposer nodes_auto
python3 -m data_engine apply --type node_packages --dry-run
python3 -m data_engine apply --type node_packages
python3 -m data_engine review --type node_packages   # 未达 auto 条件的包
```
