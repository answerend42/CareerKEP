# data_engine 流水线（按步骤）

端到端把「小图谱 + 少语料」扩成「可用图谱 + 丰富 mention」。每一步对应目录与 CLI 如下。

```text
Step 0  配置          config.json / config.py
          │
Step 1  语料抓取      corpus/          →  CLI: run, fetch, verify
          │  输出: preprocess/raw_sources/web/
          │        data_engine/output/roadmap_struct/
          ▼
Step 2  文本抽取      preprocess/      →  python -m preprocess
          │  输出: preprocess/output/mentions.json, document_entities.json, …
          ▼
Step 3  生成候选      proposers/       →  CLI: propose
          │  中间: data_engine/output/proposals/*.json
          ▼
Step 4  写入图谱      graph/           →  CLI: apply, review, rollback
          │  输出: backend/data/seeds/, aliases.json
          ▼
Step 5  校验与可视化   graph/viz.py     →  CLI: viz；backend validate-graph
```

## Step 0 — 配置

| 文件 | 作用 |
|------|------|
| `config.json` | 唯一配置：sources、proposers、限流、路径 |
| `config.py` | 加载为 `DataEngineConfig` |
| `core/paths.py` | 仓库内绝对路径常量 |

## Step 1 — 语料抓取（`corpus/`）

**不改 seeds**，只增加 preprocess 可读的文档。

| 顺序 | 模块 | 作用 |
|------|------|------|
| 1a | `corpus/targets.py` | 从 seeds+aliases 生成抓取目标与查询词 |
| 1b | `corpus/sources/*` | 各 API：plan_queries → fetch → to_documents |
| 1c | `corpus/http_client.py` + `cache.py` | 限流、重试、sqlite 缓存 |
| 1d | `corpus/normalizer.py` | 长文切片、HTML 清洗 |
| 1e | `corpus/doc_id.py` + `doc_writer.py` | doc_id 命名空间、落盘守门 |
| 1f | `corpus/struct_writer.py` | roadmap 结构 JSON（供扩图） |
| 1g | `corpus/pipeline.py` | 编排上述步骤；`run_report.json` |

**CLI**：`run` · `fetch` · `list-targets` · `verify` · `clean-cache`

## Step 2 — preprocess（仓库外）

```bash
python3 -m preprocess --input-dir preprocess/raw_sources --output-dir preprocess/output
```

产出 `mentions.json`、`document_entities.json` 等，供 Step 3 读取。

## Step 3 — 生成扩图候选（`proposers/`）

| Proposer | 读什么 | 写什么 |
|----------|--------|--------|
| `aliases` | mentions | `proposals/aliases.json` |
| `edges_cooccurrence` | document_entities | `proposals/edges.json` |
| `edges_roadmap` | `output/roadmap_struct/` | `proposals/roadmap_edges.json` |
| `nodes` | gh 语料挖词 | `proposals/nodes.json`（人审） |
| `nodes_auto` | gh + 规则/共现 | `proposals/node_packages.json` |

读写中间文件：`proposals/store.py`（`core/package.py` 定义 `NodePackage`）。

**CLI**：`propose` · `propose --proposer <name>`

## Step 4 — 写入 runtime 图谱（`graph/`）

| 模块 | 作用 |
|------|------|
| `graph/applier.py` | 备份 → append 写 seeds → graph_quality 校验 → 失败回滚 |
| `graph/packages.py` | `apply_node_packages` |
| `graph/review.py` | 人工审核未 auto 的候选 |

**CLI**：`apply` · `review` · `rollback` · `list-backups`

大批量策划扩图：`scripts/v5_balanced_batch.py`（直接 `apply_batch`）。

## Step 5 — 校验与可视化

```bash
python3 -m backend.app.main validate-graph
python3 -m data_engine viz
```

输出：`data_engine/output/graph_view.html`

## 子包一览

| 目录 | 流水线步骤 | 是否改 seeds |
|------|------------|:------------:|
| `corpus/` | Step 1 | 否 |
| `proposers/` | Step 3 | 否（只写 proposals） |
| `proposals/` | Step 3 存储 | 否 |
| `graph/` | Step 4–5 | 是 |
| `core/` | 全程共享 | — |
| `scripts/` | Step 4 批量 | 是 |

根目录 `pipeline.py`、`doc_writer.py` 等为**兼容 shim**，新代码请用 `data_engine.corpus.*`。
