# data_engine

> CareerKEP 的**语料 + 图谱**自动扩充模块。从结构化公开 API 抓回正文、自动挖出新别名/新边、半自动加新节点——全部 stdlib only、事务式落地、失败自动回滚。

```
nodes  54 → 151    edges  118 → 328    alias entries  170 → 361    mentions  91 → 126,907
                                                                             (8.2× over V2)
```

## 目录

- [目录结构](#目录结构)
- [模块说明（core / proposals / graph / nodes_auto）](#模块说明core--proposals--graph--nodes_auto)
- [它能做什么](#它能做什么)
- [30 秒上手](#30-秒上手)
- [两套子系统](#两套子系统)
- [完整工作流](#完整工作流)
- [CLI 参考](#cli-参考)
- [Proposer 自动化矩阵](#proposer-自动化矩阵)
- [来源（Source）](#来源source)
- [配置](#配置)
- [设计要点](#设计要点)
- [批量扩图（`apply_batch`）](#批量扩图apply_batch)
- [离线可视化（`viz`）](#离线可视化viz)
- [安全与回滚](#安全与回滚)
- [测试](#测试)
- [常见问题](#常见问题)
- [扩展开发](#扩展开发)
- [实测扩图历程](#实测扩图历程)

---

## 目录结构

模块按 **语料链 / 扩图链** 两条子系统组织（完整树见 [`STRUCTURE.md`](STRUCTURE.md)）：

```
data_engine/
├── cli.py, config.json          # 入口与配置
│
├── 【语料链】pipeline.py, targets.py, http_client.py, cache.py,
│              doc_id.py, normalizer.py, doc_writer.py, struct_writer.py, sources/
│
├── 【扩图链】core/, proposals/, proposers/, graph/, scripts/
│
├── 根目录 shim                  # applier / review / viz / proposals_io 转发
├── tests/
└── output/                      # proposals/, graph_view.html, run_report.json
```

| 子系统 | 包 / 模块 | 职责 |
| --- | --- | --- |
| **语料链** | `pipeline`, `sources/*`, `http_client`, `cache`, `doc_writer`… | 抓 API → 落盘 `preprocess/raw_sources/web/` |
| **扩图链** | [`core/`](core/) | [`NodePackage`](core/package.py)、[`paths`](core/paths.py) |
| | [`proposals/`](proposals/) | [`store.py`](proposals/store.py)：proposals 中间 JSON |
| | [`proposers/`](proposers/) | 候选生成；[`nodes_auto/`](proposers/nodes_auto/) 半自动 evidence |
| | [`graph/`](graph/) | [`applier`](graph/applier.py)、[`packages`](graph/packages.py)、[`review`](graph/review.py)、[`viz`](graph/viz.py) |
| | [`scripts/`](scripts/) | curated 批量（如 [`v5_balanced_batch.py`](scripts/v5_balanced_batch.py)） |
| 兼容 | 根目录 shim | 旧 import 仍可用 |

---

## 模块说明（core / proposals / graph / nodes_auto）

### `core.NodePackage`——自动加节点的原子单元

单独 `apply_nodes` 加 evidence 会因「无出边」被 [`graph_quality`](../backend/app/services/graph_quality.py) 拒绝。`NodePackage` 把 **node + 必选边 + 可选别名** 绑在一起，经 [`graph.applier.apply_batch`](graph/applier.py) 一次事务写入。

| 字段 | 含义 |
| --- | --- |
| `package_id` | 如 `pkg::redis` |
| `node` / `edges` / `aliases` | 标准 [`Candidate`](proposers/candidate.py) |
| `auto_eligible` | 是否允许 `apply --type node_packages` 自动落地 |

落盘：`data_engine/output/proposals/node_packages.json`。

### `proposers.nodes_auto`——半自动 evidence 扩图

| 文件 | 作用 |
| --- | --- |
| [`corpus_index.py`](proposers/nodes_auto/corpus_index.py) | **单次**扫描 `preprocess/raw_sources/web/gh/`（约 151 个 JSON），建 `token → 父实体共现` 索引 |
| [`rules.py`](proposers/nodes_auto/rules.py) | `config.proposers.nodes_auto.parent_rules` 正则 → 父节点 |
| [`rule_boost.py`](proposers/nodes_auto/rule_boost.py) | 对命中规则的低频词补候选（避免被 TF top_k 截断） |
| [`parent_attach.py`](proposers/nodes_auto/parent_attach.py) | 规则优先；否则用共现索引 + `min_parent_margin` 判定 |
| [`discovery_filters.py`](proposers/discovery_filters.py) | 过滤 README 高频英文词，只留像技术名的 token |
| [`builder.py`](proposers/nodes_auto/builder.py) | 组装 `NodePackage`（evidence + supports 边 + 别名） |
| [`proposer.py`](proposers/nodes_auto/proposer.py) | `NodeAutoProposer.propose_packages()` |

**与 `NodeProposer` 的分工**：

| | [`nodes`](proposers/nodes.py) | [`nodes_auto`](proposers/nodes_auto/) |
| --- | --- | --- |
| 输出 | `proposals/nodes.json` | `proposals/node_packages.json` |
| 自动应用 | 否（必 review） | 仅高置信 **evidence**（默认最多 10 个/次） |
| 父节点 | `evidence.suggested_parent` 供人工参考 | 自动写 `supports` 边 |

**启用方式**（默认 `enabled: false`）：

```bash
# config.json → "proposers.nodes_auto.enabled": true
python3 -m data_engine propose --proposer nodes_auto
python3 -m data_engine apply --type node_packages --dry-run
python3 -m data_engine apply --type node_packages
python3 -m data_engine review --type node_packages   # 未达 auto 条件的包
```

Windows 本机示例：`py -3.12 -m data_engine ...`（需 Python ≥ 3.10）。

**耗时说明**：`nodes_auto` 会扫描约 151 个 gh 语料文件 **2 遍**（建索引 + 挖 token），通常 **30–60 秒**；若超过 10 分钟，检查是否在跑 `preprocess` 或全量 `propose`（五个 proposer 串联）。

**已跑通示例**（`enabled: true` 时）：

```bash
py -3.12 -m data_engine propose --proposer nodes_auto   # → 4 auto packages（agent/protocol/…）
py -3.12 -m data_engine apply --type node_packages --dry-run
py -3.12 -m data_engine apply --type node_packages      # 写入 seeds + aliases
py -3.12 -m backend.app.main validate-graph
```

### `graph` 子包

| 模块 | 说明 |
| --- | --- |
| [`graph.applier`](graph/applier.py) | `apply_aliases` / `apply_edges` / `apply_nodes` / **`apply_batch`**、回滚 |
| [`graph.packages`](graph/packages.py) | **`apply_node_packages()`**——读 `node_packages.json` 批量落地 |
| [`graph.review`](graph/review.py) | 交互审核；接受 **evidence 节点** 时若有 `suggested_parent` 自动走 `apply_batch` |
| [`graph.viz`](graph/viz.py) | 离线 SVG 图谱 |

---

## 它能做什么

把"34 节点 / 91 mention 的玩具图谱"喂成"151 节点 / 12 万 mention / 10 个职业子树的可用图谱"，端到端自动化。两套独立可用的子系统：

| 子系统 | 输入 | 输出 | 风险 |
| --- | --- | --- | --- |
| **语料抓取** | 现有图谱节点 + 别名 | preprocess 认识的 JSON 文档 | 零——不动图谱 |
| **图谱扩展** | preprocess 信号 + roadmap 结构 + 人工策划 | seeds + aliases 增量写入 | 事务式 + 自动回滚兜底 |

三条硬约束（跟 backend/preprocess 风格对齐）：

1. **stdlib only**——`urllib`/`json`/`html.parser`/`hashlib`/`sqlite3`，零第三方依赖
2. **追加式写入**——永不覆盖手工权威条目；写盘前必先快照到 `data_engine/.cache/seed_backups/<ts>/`
3. **只走结构化公开 API**——Wikipedia REST、GitHub API、roadmap.sh JSON、O\*NET 等；不爬通用搜索结果，不爬招聘站

---

## 30 秒上手

```bash
# 0. (可选) 设 GitHub token 解锁 5000/h（不设走 60/h，几个 entity 就限速）
cp data_engine/.env.example data_engine/.env   # 改里面的 GITHUB_TOKEN
set -a; . data_engine/.env; set +a

# 1. 抓语料
python3 -m data_engine run --mode full --limit-per-target 2

# 2. 让 preprocess 消化
python3 -m preprocess

# 3. 跑提案器找扩图候选
python3 -m data_engine propose

# 4. 自动落地高置信候选（事务式 + 失败回滚）
python3 -m data_engine apply

# 5. 看效果
python3 -m data_engine viz
xdg-open data_engine/output/graph_view.html
```

5 步从语料抓取一直跑到看到新图谱。每步都可独立重跑、可回滚。

---

## 两套子系统

### A. 语料抓取（`run` / `fetch`）

```
backend/data/seeds/nodes.json + aliases.json
              │ (preprocess.catalog 复用，零侵入)
              ▼
       targets.build_targets ──▶ Target(entity_id, queries, layer, ...)
              │
              ▼
   sources/{wiki,github,roadmap,onet}.plan_queries ──▶ FetchPlan(query, url)
              │
              ▼
        http_client.HttpClient (urllib + 令牌桶 + 指数退避 + sqlite cache)
              │
              ▼
   sources/*.to_documents ──▶ WebDocument
              │ (normalizer.split_long 长文按句号回溯切片)
              ▼
       doc_writer.write_documents（强制 license 字段、按 doc_id 合并）
              │
              ▼
   preprocess/raw_sources/web/<source>/<entity>.json
              │
              ▼
       python3 -m preprocess  ←  既有命令、零代码改动
              │
              ▼
   preprocess/output/{entities, mentions, document_entities, ...}.json
```

**契约**：抓回来的文档与 [`preprocess/raw_sources/demo_corpus.json`](../preprocess/raw_sources/demo_corpus.json) 通过 doc_id 命名空间隔离（`web-<source>-<entity>-<sha1>`），preprocess 一行代码不改自动消费。

### B. 图谱扩展（`propose` / `apply` / `review` / `apply_batch`）

```
preprocess/output/{mentions, document_entities, alias_ambiguity}.json
data_engine/output/roadmap_struct/<role>.json   (V3+ roadmap fetcher 副产物)
                                │
                                ▼
              proposers/{aliases, edges_cooccurrence, edges_roadmap, nodes}
                                │
                                ▼
            data_engine/output/proposals/{aliases, edges, roadmap_edges, nodes}.json
                                │
              ┌─────────────────┴─────────────────┐
              ▼                                   ▼
       自动应用通道                          人工审核通道
       (apply_batch / apply)                (review --type nodes)
              │                                   │
              ▼                                   ▼
       backup → write → backend.graph_quality.validate
              │
        ┌─────┴─────┐
        ▼           ▼
   通过：保留    失败：恢复 backup
        │
        ▼
   backend/data/seeds/{nodes, edges}.json + dictionaries/aliases.json
```

**契约**：所有写入先备份 → 写盘 → in-process 校验。任何 `GraphValidationError` 立即从备份恢复，永远不会留下半成品。

---

## 完整工作流

一次完整迭代的标准动作：

```bash
# Phase 1: 语料层
set -a; . data_engine/.env; set +a
python3 -m data_engine run --mode full --limit-per-target 2
python3 -m preprocess

# Phase 2: 自动扩图（别名 + 边；可选半自动 evidence 节点包）
python3 -m data_engine propose              # 或拆开：--proposer aliases 等
# 若已开启 nodes_auto.enabled：
#   python3 -m data_engine propose --proposer nodes_auto
python3 -m data_engine apply --dry-run
python3 -m data_engine apply                # 含 node_packages（若已 propose）

# Phase 3: 人工审核
python3 -m data_engine review --type nodes          # 非 evidence / 无可靠父节点
python3 -m data_engine review --type node_packages  # nodes_auto 未 auto 的包

# Phase 4: 大批量人工策划（可选）—— 比 review CLI 快一个数量级
PYTHONPATH=. python3 data_engine/scripts/v5_balanced_batch.py

# Phase 5: 兜底校验 + 可视化
python3 -m backend.app.main validate-graph
python3 -m data_engine viz
```

任意步骤失败都可独立重做，不会污染前面的状态。

---

## CLI 参考

| 命令 | 作用 | 何时用 |
| --- | --- | --- |
| `run [--mode full\|incremental] [--sources X,Y] [--limit-per-target N] [--dry-run]` | 跑抓取 pipeline | 主要的语料获取入口 |
| `list-targets [--mode incremental]` | 打印目标 + 查询词，不发请求 | 估算抓取规模 |
| `fetch --source X --query "..."` | 单点调试某个查询 | 排查 fetcher 行为 |
| `verify` | 扫 `raw_sources/web/` 校验 schema + doc_id 唯一性 | CI 兜底 |
| `clean-cache [--source X]` | 清 sqlite 缓存（按 fetcher 自带 hints 精确匹配） | 强制重抓 |
| `propose [--proposer X]` | 生成扩图候选；`nodes_auto` → `node_packages.json` | 扩图前置 |
| `apply [--type X] [--dry-run]` | 落地 auto 候选；**`node_packages`** 走 `apply_batch` | 自动扩图主入口 |
| `review --type {aliases,edges,roadmap_edges,node_packages,nodes}` | 交互审核；`nodes` 接受 evidence 时可带父边 batch 写入 | 人工兜底 |
| `list-backups` | 列出 `data_engine/.cache/seed_backups/` 的所有快照 | 看历史 |
| `rollback --to <timestamp>` | 从指定快照恢复 seeds | 反悔 |
| `viz [--output PATH]` | 把 seeds 渲染成离线 SVG 网页 | 可视化检查 |

`--mode incremental` 读 `preprocess/output/uncovered_entities.json` 只抓未覆盖节点；该文件不存在时软降级为 `full`。

---

## Proposer 自动化矩阵

| Proposer | 类型 | 信号源 | 默认自动应用 | 输出文件 |
| --- | --- | --- | --- | --- |
| [`AliasProposer`](proposers/aliases.py) | alias | `mentions.json` | 高置信 + 无 collision | `aliases.json` |
| [`CooccurrenceEdgeProposer`](proposers/edges_cooccurrence.py) | edge | `document_entities.json` 共现 | `cooc ≥ 30` + 层序合法 | `edges.json` |
| [`RoadmapEdgeProposer`](proposers/edges_roadmap.py) | edge | `roadmap_struct/*.json` | 几乎全 auto | `roadmap_edges.json` |
| [`NodeProposer`](proposers/nodes.py) | node | [`discovery.py`](proposers/discovery.py) 挖 gh token | **永不 auto** | `nodes.json` |
| [`NodeAutoProposer`](proposers/nodes_auto/proposer.py) | **node_package** | discovery + [`corpus_index`](proposers/nodes_auto/corpus_index.py) + `parent_rules` | 仅 **evidence** 且父节点达标；`max_auto_per_run` 封顶 | **`node_packages.json`** |

`nodes_auto` 配置项（[`config.json`](config.json) → `proposers.nodes_auto`）：

| 键 | 默认 | 含义 |
| --- | ---: | --- |
| `enabled` | `false` | 总开关 |
| `min_doc_count` / `min_token_count` | 12 / 40 | 比 `nodes` 更严，减少候选 |
| `min_parent_cooc` / `min_parent_cooc_ratio` | 5 / 0.55 | 共现父节点阈值 |
| `max_auto_per_run` | 10 | 单次最多自动落地包数 |
| `parent_rules` | 见 config | 正则 → 父 entity_id（优先于共现） |

**设计原则**：`ability` / `composite` / `direction` / `role` 仍应用 [`apply_batch`](graph/applier.py) 策划脚本或人工 review；`nodes_auto` 只自动加「工具型 evidence + 一条 supports 父边」。

---

## 来源（Source）

| Source | 入口 API | 落盘 | License | 备注 |
| --- | --- | --- | --- | --- |
| [`wikipedia`](sources/wikipedia.py) | `https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}` | `web/wiki` | `CC-BY-SA-4.0` | 默认 en+zh；命中 disambiguation 页自动丢弃 |
| [`github`](sources/github.py) | `search/repositories?q=...` + `repos/{owner}/{repo}/readme` | `web/gh` | 随仓库（默认 `unknown-see-repo`，记 `repo_full_name` + `stars` + `primary_language`） | 设 `GITHUB_TOKEN` 解锁 5000/h，否则 60/h |
| [`roadmap`](sources/roadmap.py) | `raw.githubusercontent.com/nilbuild/developer-roadmap/.../<role>.json` | `web/roadmap` + `output/roadmap_struct/` | `Apache-2.0` | 仅 role/direction/composite 层节点参与；同步保留原始 react-flow JSON 给 RoadmapEdgeProposer 用 |
| [`onet`](sources/onet.py) | — | — | — | 占位，默认 `enabled: false` |

> roadmap.sh 仓库 2024 年从 `kamranahmedse/*` 迁到 `nilbuild/*`，URL 已更新；旧 URL 会 404。

### GitHub Token 配置

token 唯一作用是把限速从 60/h 提到 5000/h。**生成时 scope 全部不勾**——公共 repo 只读 API 不需要任何 scope，最小权限最安全。

```bash
# 生成: https://github.com/settings/tokens?type=beta （或 classic 也行）
cp data_engine/.env.example data_engine/.env
# 编辑 .env，把 GITHUB_TOKEN=ghp_xxx 换成真值
set -a; . data_engine/.env; set +a
```

token 只读 `os.environ.get("GITHUB_TOKEN")`，不进 config.json、不进任何输出文件、不进 cache。`.env` 已被 [`data_engine/.gitignore`](.gitignore) 忽略，绝不会进 git。

---

## 配置

[`config.json`](config.json) 是模块的唯一配置入口，启动时由 [`config.py`](config.py) 加载为不可变 dataclass。

```jsonc
{
  // 全局
  "user_agent": "CareerKEP-DataEngine/0.1",
  "timeout_seconds": 15,
  "max_retries": 3,
  "backoff_base_seconds": 1.5,
  "global_qps": 1.0,                          // 全局限流上限
  "output_root": "preprocess/raw_sources/web", // 落盘根目录
  "cache_path": "data_engine/.cache/http_cache.sqlite",
  "max_chars_per_doc": 8000,                  // 切片阈值
  "split_overlap": 200,                       // 切片重叠（保留上下文）

  // 各 source 独立配置；每个 source 一个独立 HttpClient，限流互不干扰
  "sources": {
    "wikipedia": {"enabled": true, "languages": ["en","zh"], "qps": 1.0},
    "github":    {"enabled": true, "qps": 0.5, "token_env": "GITHUB_TOKEN"},
    "roadmap":   {"enabled": true, "qps": 0.5},
    "onet":      {"enabled": false, "qps": 0.5}
  },

  // 查询词扩展
  "query_expansion": {
    "use_aliases": true,                      // 是否把 aliases.json 也当查询
    "extra_terms": {                          // 给中文 label 配英文同义词
      "python": ["Python (programming language)"],
      "ml_engineer": ["Machine learning engineer"]
      // ...
    }
  },

  // 增量模式
  "incremental": {
    "uncovered_report": "preprocess/output/uncovered_entities.json",
    "skip_if_recent_hours": 168               // sqlite cache 命中 TTL
  },

  // Proposer 阈值
  "proposers": {
    "aliases": {
      "auto_apply_confidence_min": 0.85,
      "auto_apply_doc_count_min": 3,
      "review_doc_count_min": 2
    },
    "edges_cooccurrence": {
      "auto_apply_cooc_min": 30,
      "review_cooc_min": 8,
      "default_weight": 0.6
    },
    "edges_roadmap": {"default_weight": 0.7},
    "nodes": {
      "min_doc_count": 8,
      "min_token_count": 30,
      "top_k": 60
    }
  }
}
```

调阈值的常用动作：
- **`extra_terms` 命中率低**：英文维基命中失败时往这里补英文同义词，下次跑 `run --sources wikipedia` 立刻见效
- **想多收一些边**：把 `edges_cooccurrence.auto_apply_cooc_min` 从 30 调到 20-25，下次 `apply` 会多落地几十条边
- **想看更多新节点候选**：调高 `nodes.top_k` 或调低 `nodes.min_doc_count`

---

## 设计要点

### 落盘契约

- **doc_id 命名空间隔离**：`web-<source>-<entity>-<sha1[:12]>[-c<chunkIdx>]`。`web-` 前缀让 data_engine 的文档与 demo_corpus.json 现有 doc_id 永不冲突
- **doc_writer 是落盘的唯一守门人**：[`doc_writer.py`](doc_writer.py) 强制 `license` 字段、强制 `source` 必须以 `web/` 开头、强制 `entity_hint == 目录 entity_id`；同 entity 多份文档合并到同一个 `<entity>.json` 的 `documents` 数组，按 doc_id 去重 + 排序，避免无意义 git diff
- **长文本切片不切坏句子**：[`normalizer.py`](normalizer.py) 的 `split_long` 在 `max_chars` 边界回溯到最近的句号/换行；切片用 `-c<idx>` 后缀生成稳定 doc_id

### HTTP 抓取

- **HTTP 客户端是唯一外部出口**：[`http_client.py`](http_client.py) 内置令牌桶（`min(global_qps, source.qps)`）+ 指数退避（429/503）+ jitter；所有 source 必须从注入的 `HttpClient` 走
- **失败不阻塞**：单条 plan 失败计入 `run_report.failed[]`，pipeline 继续；exit code 在 `cli.py` 里依据 `failures` 是否为空决定
- **断点续抓**：[`cache.py`](cache.py) sqlite 单表记 `(url, status, etag, last_modified, doc_id, fetched_at, error)`，重跑跳过 success URL（默认 168h TTL）
- **cache key = 完整 URL**：含 query string。**所有共用 base URL 的 source 必须把 query params 烘进 `FetchPlan.url`**，否则不同查询会互相覆盖 cache（这是 GitHub search API 当年踩过的大坑）

### 图谱扩展

- **append-only**：proposers/applier 永不删改原条目。手工权威条目和 V3+ 追加条目混存，靠"已有则跳过"识别；rollback 通过备份目录回到任意历史状态
- **每个候选带 signature**：`alias::<entity>::<text>` / `edge::<src>::<rel>::<tgt>` / `node::<id>`。`proposals/applied.json` 与 `proposals/rejected.json` 记录这些 signature 当黑/白名单——重复 propose 不会再灌相同候选给你
- **applier in-process 校验**：写盘后调用 backend 自身的 [`graph_loader`](../backend/app/services/graph_loader.py) + [`graph_quality`](../backend/app/services/graph_quality.py)；任何 `GraphValidationError` 触发回滚，不需要 subprocess

### 跨层规则（实战踩过的坑）

graph_quality 的层间规则——加边/加节点时必须遵守，否则被拒：

| 关系 | 允许 | 不允许 |
| --- | --- | --- |
| evidence → ability/composite/direction/role | ✅ 跨层 | — |
| ability → composite/direction/role | ✅ 跨层 | ability → ability |
| composite → direction/role | ✅ | composite → composite |
| direction → role | ✅ | direction → direction |
| 任意层 → 同层 | ❌ 全部禁止 | — |
| 高层 → 低层 | ❌ 全部禁止（DAG 单向上传）| — |

写 curated batch 时如果误用 evidence→evidence（如想把 graphql 挂到 api_design），applier 会校验失败并回滚——把目标改成 ability 层（如 backend_tech_stack）即可。

---

## 批量扩图（`apply_batch`）

[`applier.apply_batch`](applier.py) 是混合批量入口，**单事务原子写入**节点 + 边 + 别名。这是整个 V3-V5 扩图的主力工具——它解决了一个核心问题：

> **死锁场景**：单独调 `apply_nodes` 加新 evidence 节点时，因为新节点没有出边，graph_quality 判 "evidence 不能影响任何非 evidence 节点" 直接拒；但单独调 `apply_edges` 又不能引用尚未存在的节点。

`apply_batch` 在校验前一次性写完节点 + 边 + 别名，把 evidence 节点和它的出边作为单一事务考虑——校验失败时三个文件一起恢复。

最小调用：

```python
from data_engine import applier
from data_engine.proposers.candidate import Candidate

nodes = [Candidate(
    kind="node",
    payload={"id": "redis", "label": "Redis", "layer": "evidence",
             "aggregator": "source", "cap": 1.0},
    confidence=1.0, auto_apply_eligible=True, source_proposer="curated",
)]

edges = [Candidate(
    kind="edge",
    payload={"source": "redis", "target": "database_practice",
             "relation": "supports", "weight": 0.7},
    confidence=1.0, auto_apply_eligible=True, source_proposer="curated",
)]

aliases = [Candidate(
    kind="alias",
    payload={"entity_id": "redis", "alias": "缓存"},
    confidence=1.0, auto_apply_eligible=True, source_proposer="curated",
)]

report = applier.apply_batch(nodes, edges, aliases)
print(report.to_dict())
# {'applied_nodes': 1, 'applied_edges': 1, 'applied_aliases': 1, 'skipped': 0, 'failed': 0,
#  'backup_dir': '/.../seed_backups/20260518T...Z', 'errors': []}
```

### 各层节点的参数模板

```python
# evidence (atomic skill/tool)
{"id": ..., "label": ..., "layer": "evidence",
 "aggregator": "source", "cap": 1.0}

# ability (foundational competency)
{"id": ..., "label": ..., "layer": "ability",
 "aggregator": "weighted_sum_capped", "cap": 1.0,
 "min_support_count": 1}  # 1-2

# composite (cross-cutting competency)
{"id": ..., "label": ..., "layer": "composite",
 "aggregator": "soft_and", "cap": 1.0,
 "min_support_count": 2}  # 2-3

# direction (career direction)
{"id": ..., "label": ..., "layer": "direction",
 "aggregator": "penalty_gate", "cap": 1.0,
 "required_threshold": 0.5,  # 0.45-0.5
 "penalty_floor": 0.35}

# role (specific job title)
{"id": ..., "label": ..., "layer": "role",
 "aggregator": "hard_gate", "cap": 1.0,
 "required_threshold": 0.55}  # 0.5-0.55
```

### 模板脚本

[`scripts/v5_balanced_batch.py`](scripts/v5_balanced_batch.py) 是一份完整的模板：97 节点跨 5 层 + 127 边 + 190 别名一次性扛下来。新一轮大批量扩图的最快路径就是 copy 它然后改数据表。

```bash
PYTHONPATH=. python3 data_engine/scripts/v5_balanced_batch.py
```

---

## 离线可视化（`viz`）

前端的"图谱传播"页是 5 列卡片堆叠（每层一列、显示分数 bar），不是网络图，且需要先提交 evidence 才有数据。要看**当前 seeds 完整结构**用 viz：

```bash
python3 -m data_engine viz
# 输出: data_engine/output/graph_view.html
```

[`viz.py`](viz.py) 渲染一份纯 SVG 自包含网页（**无 JS、无 CDN、无外部依赖**）。5 层从左到右排开，节点之间画弧线，按 relation 上色：

| 关系 | 颜色 |
| --- | --- |
| supports | 灰 #9aa6c4 |
| evidences | 蓝 #5fb6d4 |
| requires | 红 #e26c6c |
| prefers | 绿 #9bd07d |
| inhibits | 橙 #e2a36c |

data_engine 引入的节点（V3+V4 curated）用金色高亮。

WSL 上用 Windows 浏览器看时，`file://` 协议跨 WSL/Windows 边界经常打不开。起本地 http server：

```bash
cd data_engine/output && python3 -m http.server 8181 --bind 127.0.0.1
# Windows Chrome 打 http://127.0.0.1:8181/graph_view.html
```

---

## 安全与回滚

每次 `apply` / `apply_batch` 写盘前：

1. 复制 nodes.json + edges.json + aliases.json 到 `data_engine/.cache/seed_backups/<UTC-timestamp>/`
2. 把候选写到 seeds 文件
3. 调 `backend.app.services.graph_quality.validate_graph_quality` in-process 校验
4. 任何 `GraphValidationError` → 立即从备份恢复三个文件
5. 报错信息进 `report.errors[]` 让调用方能查

手动回滚：

```bash
python3 -m data_engine list-backups
# 输出每个备份的时间戳 + 包含的文件

python3 -m data_engine rollback --to 20260518T080501Z
# 三个 seed 文件一起恢复
```

新节点 / 新边的 dedup：

- 节点撞 id：`apply_batch` 内部 `existing_node_ids` 检查，撞到就 skip 不覆盖
- 边重复：`(source, target, relation)` 三元组去重
- 别名 collision：lower-case 比对去重；同一 surface 出现在多 entity 会被 AliasProposer 在 propose 阶段自动剔除（避免 "数据" 这种灾难）

---

## 测试

```bash
# 仓库根目录
python3 -m unittest discover -s data_engine/tests

# 仅新组件
python3 -m unittest data_engine.tests.test_nodes_auto -v
```

75+ testcase，离线可跑。新增 [`test_nodes_auto.py`](tests/test_nodes_auto.py) 覆盖：`parent_rules`、`NodePackage` 序列化、`NodeAutoProposer` 开关与打包逻辑。

| 测试文件 | 覆盖 |
| --- | --- |
| **`test_nodes_auto.py`** | **规则父节点、NodePackage、proposer 开关与 mock 打包** |
| `test_applier.py` | 事务写入 / 回滚（针对 `graph.applier`） |
| `test_proposers.py` | alias collision、边层序、NodeProposer 不 auto |
| `test_doc_id.py` … `test_pipeline_e2e.py` | 语料链路与其它 proposer |

**冒烟（需已存在 web/gh 语料）**：

```bash
# 1. 临时打开 nodes_auto（或改 config.json enabled=true）
python3 -m data_engine propose --proposer nodes_auto
python3 -m data_engine apply --type node_packages --dry-run
```

---

## 常见问题

### 抓回来的文档没出现在 mention 里

最可能：preprocess 没重跑。语料抓完必须跑一次 `python3 -m preprocess` 才能让 mention 数更新。

第二可能：节点 alias 太少 / 太通用，preprocess 抽不出 surface。检查 `aliases.json` 里这个 entity 至少有 2 条中英文常见表面变体。

### `apply` 报 `evidence 'X': 不能影响任何非 evidence 节点`

加新 evidence 节点时没有同步加它的出边。**改用 `apply_batch` 而不是 `apply_nodes`**——把节点和它的至少一条 supports 边作为同事务提交。

### `clean-cache --source X` 删了 0 行

短名（如 GitHub 的 `gh`）不一定出现在真实 URL 里（"github.com" 不含 "gh" 子串）。每个 Fetcher 类有 `cache_url_hints = (...)` 属性专门给 clean-cache 用——如果你写新 source 没声明这个属性，按 source 清不会工作。改 fetcher 加 `cache_url_hints` 即可。

### GitHub 抓到一半 429

未设 `GITHUB_TOKEN`，60/h 限速跑光了。要么等一小时，要么按上面的"GitHub Token 配置"加 token（5000/h）。失败的 plan 已自动进 `run_report.failed[]`，不会污染已成功的部分；下次重跑只补未成功的。

### `apply` dry-run 显示有候选，但真跑 0 落地

候选不达 auto 阈值（看 `auto_apply_eligible` 字段）。两个选择：
1. 调低 `config.json` 里 proposer 的 `auto_apply_*` 阈值
2. 用 `python3 -m data_engine review --type X` 人工过

### 跑 `viz` 后 graph_view.html 在 WSL 里 Chrome 打不开

`file://` 协议跨 WSL/Windows 边界经常失败。起本地 server：`cd data_engine/output && python3 -m http.server 8181`，Chrome 打 `http://127.0.0.1:8181/graph_view.html`。

### preprocess 跑得很慢（30+ 分钟）

正常。在 150 节点 + 1700 文档量级时，preprocess 的 mention 抽取 + 消歧是 O(节点 × 文档 × 平均 surface 数)，几十分钟内属正常。优化空间在 preprocess 自己，与 data_engine 无关。

### `propose` / `nodes_auto` 跑很久、终端无输出

- **不是卡死**：默认几乎不打进度日志；`nodes_auto` 会顺序执行「建共现索引 → 挖 token → 逐条推断父节点」。
- **不要**在无 `--proposer` 时误以为只跑了 `nodes_auto`——`python3 -m data_engine propose` 会串行跑 **5 个** proposer（含扫全库的 `nodes`）。
- 建议：拆开跑 `propose --proposer nodes_auto`；调试时把 `top_k`、`max_auto_per_run` 调小。
- 若仍要跑全量 `nodes`，也会扫一遍 151 个 `web/gh/*.json`，约 1–2 分钟量级。

---

## 扩展开发

### 新增 source

```bash
cp data_engine/sources/wikipedia.py data_engine/sources/your_source.py
```

改三处：

1. `class YourSourceFetcher` 的 `name` / `short_name` / `cache_url_hints`（**必须**，否则 clean-cache 无效）
2. `plan_queries(target, source_cfg)` 返回 `List[FetchPlan]`，**如果共用 base URL 必须把 query params 烘进 `FetchPlan.url`**
3. `to_documents(target, plan, raw, source_cfg)` 把 raw 解析成 `List[WebDocument]`，**必须给 `license` 字段赋具体值**（不能空）

最后在 [`sources/__init__.py`](sources/__init__.py) 加一行 `from . import your_source` 触发 `register()`。

跑请求**必须**用注入的 `http: HttpClient`，不要自己 `urlopen`——否则跳过限流/重试/缓存。

### 新增 entity

直接改 [`backend/data/seeds/nodes.json`](../backend/data/seeds/nodes.json) 加节点（按仓库的图谱变更流程）。data_engine 下次跑 `run` 自动接上——`targets.py` 通过 [`preprocess/catalog.py`](../preprocess/catalog.py) 复用同一份目录加载逻辑，零代码改动。

如果是大批量加节点（10+），用 [`scripts/v5_balanced_batch.py`](scripts/v5_balanced_batch.py) 模板更稳。

### 新增 license 类型

直接在新 source 的 `to_documents` 里给 `WebDocument.license` 赋具体值即可。没有许可清单的硬约束，但**禁止留空**——`doc_writer.write_documents` 会拒写。

### 追加查询词扩展

往 `config.json` 的 `query_expansion.extra_terms` 里加 entity 即可，无须改代码。常见用途：给中文 label 配英文同义词，让英文维基命中率显著提升。

---

## 实测扩图历程

基于 34 节点 / 19 alias / 91 mention 的 V2 起点，五次迭代的实测数据：

| 阶段 | nodes | edges | alias keys | aliases | mentions | 关键动作 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| V2 末尾（手工权威源） | 34 | 56 | 19 | 68 | 91 | demo_corpus.json 唯一语料 |
| V2 后 `run` + preprocess | 34 | 56 | 19 | 68 | 15,449 | wiki+roadmap+gh 全开，corpus 涨到 431 docs |
| V2 后 `apply --auto` | 34 | 98 | 34 | 129 | 15,449 | +42 cooc 边 +15 alias，全自动 |
| V3 curated batch | 44 | 108 | 34 | 129 | 15,449 | +10 evidence (pytorch/llm/git/...) |
| V4 curated batch | 54 | 118 | 54 | 170 | 15,449 | 再 +10 evidence (fastapi/redis/k8s/...) |
| V5 五层平衡扩图 | **151** | **328** | **151** | **361** | **126,907** | +97 节点跨 5 层、+210 边、6 条新职业线 |

**V5 是关键转折**：之前都在底层堆 evidence，金字塔变纺锤，前端推荐只能命中那 4 个 role。V5 重写为五层平衡——每加一批 evidence 同时建立 ability / composite / direction / role 子树，新增了 DevOps / SRE / 移动 / 安全 / 全栈 / AI Engineer 6 条职业线。最终金字塔 109/15/8/9/10。

V3+V4+V5 的 curated batch 都走 [`applier.apply_batch`](applier.py)——节点 / 边 / 别名一次性原子写入，跳过 NodeProposer 的 review CLI、把 layer 归属判断前置到脚本里。这是 review CLI 的快速通道，适合"我已经知道这批要加什么"的场景。

V5 的具体节点列表与边布线代码见 [`scripts/v5_balanced_batch.py`](scripts/v5_balanced_batch.py)，可作为后续大批量扩图的模板。
