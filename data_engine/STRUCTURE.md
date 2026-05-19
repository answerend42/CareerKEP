# data_engine 目录结构

两条子系统：**语料链**（只进 preprocess）与 **扩图链**（写 seeds）。语料相关模块仍在根目录（历史布局）；扩图相关已拆入 `core/`、`proposals/`、`graph/`、`proposers/`。

```
data_engine/
├── __main__.py              # python -m data_engine
├── cli.py                   # 子命令入口（语料 + 扩图）
├── config.json / config.py  # 唯一配置入口
│
│  ── 语料链（run / fetch）────────────────────────────────
├── pipeline.py              # run() 编排、RunStats、run_report
├── targets.py               # 从 seeds+aliases 构建 Target
├── http_client.py           # 令牌桶、退避、urllib 封装
├── cache.py                 # sqlite HTTP 缓存
├── doc_id.py                # web-<source>-<entity>-<sha1> 生成
├── normalizer.py            # split_long、html_to_text
├── doc_writer.py            # 落盘守门、合并 documents
├── struct_writer.py         # roadmap → roadmap_struct JSON
├── reporting.py             # run_report 格式化
├── sources/
│   ├── base.py              # BaseFetcher 协议、register/all_fetchers
│   ├── wikipedia.py
│   ├── github.py
│   ├── roadmap.py
│   └── onet.py              # 占位
│
│  ── 扩图链（propose / apply / review / viz）──────────────
├── core/
│   ├── paths.py             # SEED_*、PROPOSALS_DIR、WEB_GH_ROOT、BACKUP_ROOT
│   └── package.py           # NodePackage
├── proposals/
│   └── store.py             # proposals/*.json、node_packages.json、applied/rejected
├── proposers/
│   ├── base.py              # Proposer 注册
│   ├── candidate.py
│   ├── aliases.py
│   ├── edges_cooccurrence.py
│   ├── edges_roadmap.py
│   ├── nodes.py
│   ├── discovery.py
│   ├── discovery_filters.py
│   └── nodes_auto/
│       ├── corpus_index.py
│       ├── rules.py
│       ├── rule_boost.py
│       ├── parent_attach.py
│       ├── builder.py
│       └── proposer.py
├── graph/
│   ├── applier.py           # apply_*、apply_batch、rollback
│   ├── packages.py          # apply_node_packages
│   ├── review.py
│   └── viz.py
├── scripts/
│   └── v5_balanced_batch.py # V5 curated 批量扩图
│
│  ── 兼容 shim（转发到子包）────────────────────────────
├── applier.py
├── review.py
├── viz.py
└── proposals_io.py
│
├── tests/
├── output/                  # gitignore：proposals/、graph_view.html、run_report.json
└── .cache/                  # gitignore：http_cache.sqlite、seed_backups/
```

## 子包职责

| 包 | 职责 | 子系统 |
| --- | --- | --- |
| `sources/` + 根目录 pipeline 系 | 公开 API 抓语料、落盘 preprocess | 语料链 |
| `core/` | 共享类型、路径常量 | 扩图链 |
| `proposals/` | 候选中间 JSON 读写 | 扩图链 |
| `proposers/` | 从 preprocess / 语料 / roadmap 生成候选 | 扩图链 |
| `graph/` | 写 seeds、审核、可视化、回滚 | 扩图链 |
| `scripts/` | 一次性 curated batch | 扩图链 |

## 兼容层

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
python3 -m data_engine review --type node_packages
```
