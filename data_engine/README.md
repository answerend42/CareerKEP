# data_engine 模块说明

## 功能定位

`data_engine/` 是 CareerKEP 的**语料 + 图谱**扩充模块。两条职责，对应两套子系统：

1. **语料抓取链** —— 读现有图谱节点和别名当查询词，调结构化公开 API 抓回正文，标准化成 preprocess 认识的 JSON 文档，落到 [`preprocess/raw_sources/web/`](../preprocess/raw_sources/web/) 下。preprocess 流水线零改动消费。
2. **扩图链** —— 从 preprocess 的 mention/共现/歧义信号 + roadmap 结构 JSON 里挖候选（新别名、新边、新节点），事务式批量写到 [`backend/data/seeds/`](../backend/data/seeds/) + [`backend/data/dictionaries/aliases.json`](../backend/data/dictionaries/aliases.json)，失败自动从备份回滚。

设计约束：

- **新增是追加式**：永不覆盖手工原始条目；写盘前必快照到 `data_engine/.cache/seed_backups/<timestamp>/`
- **只用结构化公开 API**：Wikipedia REST、GitHub API、roadmap.sh JSON、O*NET 等；不爬通用搜索结果，不爬招聘站
- **stdlib only**：`urllib.request` + `json` + `html.parser` + `hashlib` + `sqlite3`，与 backend/preprocess "零第三方依赖" 风格保持一致

## 数据流

```
backend/data/seeds/nodes.json + aliases.json
              │ (preprocess.catalog 复用)
              ▼
       targets.build_targets ──▶ Target(entity_id, queries, layer, ...)
              │
              ▼
   各 source.plan_queries ──▶ FetchPlan(query, url, metadata)
              │
              ▼
        http_client.HttpClient (urllib + 节流 + 退避 + sqlite cache)
              │
              ▼
   各 source.to_documents ──▶ WebDocument
              │ (normalizer.split_long 长文切片)
              ▼
       doc_writer.write_documents
              │
              ▼
   preprocess/raw_sources/web/<source>/<entity>.json
              │
              ▼
       python3 -m preprocess  ←  既有命令，0 改动
              │
              ▼
   preprocess/output/{entities,entity_coverage,...}.json
```

## 入口（CLI）

所有命令从仓库根目录执行：

```bash
# 看本次会抓哪些节点 + 查询词，不发请求
python3 -m data_engine list-targets --mode full

# 看会发哪些 URL（dry-run），用于估算膨胀量
python3 -m data_engine run --mode full --dry-run --limit-per-target 3

# 真抓全部启用的 source
python3 -m data_engine run --mode full --limit-per-target 3

# 按 source 分批跑（便于排查）
python3 -m data_engine run --sources wikipedia --limit-per-target 4
python3 -m data_engine run --sources github    --limit-per-target 2
python3 -m data_engine run --sources roadmap   --limit-per-target 4

# 单点调试某个查询词
python3 -m data_engine fetch --source wikipedia --query "Python (programming language)"

# 校验已落盘文件 schema 与 doc_id 唯一性
python3 -m data_engine verify

# 清缓存（按 fetcher 自带的 cache_url_hints 精确匹配，可传 name 或 short_name）
python3 -m data_engine clean-cache --source github   # 仅删 github 相关
python3 -m data_engine clean-cache                   # 全清

# 渲染当前 seeds 为离线 SVG 网页（无 JS、无外部依赖）
python3 -m data_engine viz                           # 输出 data_engine/output/graph_view.html
```

`--mode incremental` 会读 `preprocess/output/uncovered_entities.json` 只抓没语料的节点；该文件不存在时（首跑）软降级为 `full`。

## GitHub Token（可选但强烈推荐）

GitHub source 不带 token 时走未认证速率（60 req/h），跑几个 entity 就会 429。提供 token 后涨到 5000 req/h，整轮抓取从"分钟级断断续续"变"一次跑完"。

```bash
# 1. 生成 PAT classic：https://github.com/settings/tokens
#    Note 写 "CareerKEP data_engine" 之类描述；Expiration 30 天起
#    Select scopes 全部不勾（只用于解锁速率，不需要任何 scope）

# 2. 用 .env.example 起个本地 .env
cp data_engine/.env.example data_engine/.env
# 把 ghp_xxx 换成真实 token；data_engine/.gitignore 已忽略 .env

# 3. 跑前 source 一下
set -a; . data_engine/.env; set +a
python3 -m data_engine run --sources github --limit-per-target 2
```

[`sources/github.py`](sources/github.py) 只读 `os.environ.get("GITHUB_TOKEN")`，token 不进 config.json、不进任何输出文件、不进 cache。

## 配置（`config.json`）

[`data_engine/config.json`](config.json) 是模块的唯一配置入口，启动时由 [`config.py`](config.py) 加载为不可变 dataclass。

- 全局：`user_agent`、`timeout_seconds`、`max_retries`、`backoff_base_seconds`、`global_qps`、`output_root`、`cache_path`、`max_chars_per_doc`、`split_overlap`。
- `sources.<name>`：`enabled`、`qps`，以及该 source 的特有字段（如 wikipedia 的 `languages`、github 的 `token_env`、roadmap 的 `roles`）。每个 source 一个独立 HttpClient，限流互不干扰。
- `query_expansion`：
  - `use_aliases`：是否把 [`aliases.json`](../backend/data/dictionaries/aliases.json) 里的别名也当查询词。
  - `extra_terms`：`{entity_id: ["English term", ...]}`，给中文 label 配英文同义词，让英文维基命中率显著提升。维护时直接追加，不需要改代码。
- `incremental.uncovered_report`：被 `--mode incremental` 读取，路径相对仓库根。
- `incremental.skip_if_recent_hours`：`HttpCache` 缓存 TTL；同 URL 在该窗口内复用 success 记录，不会重复请求。

## 已支持的来源

| name | 入口 API | 落盘 source | License | 备注 |
| --- | --- | --- | --- | --- |
| `wikipedia` | `https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}` | `web/wiki` | `CC-BY-SA-4.0` | 默认 en+zh；命中 disambiguation 页自动丢弃 |
| `github` | `search/repositories?q=...` + `repos/{owner}/{repo}/readme` | `web/gh` | 随仓库（默认 `unknown-see-repo`，记 `repo_full_name`） | 设 `GITHUB_TOKEN` 解锁 5000/h，否则 60/h |
| `roadmap` | `raw.githubusercontent.com/nilbuild/developer-roadmap/.../<role>.json` | `web/roadmap` | `Apache-2.0` | 仅 role/direction/composite 层节点参与；仓库 2024 年从 `kamranahmedse/*` 转移到 `nilbuild/*`，URL 已更新 |
| `onet` | — | — | — | 占位，默认 `enabled: false` |

## 设计要点

- **doc_id 命名空间隔离**：`web-<source>-<entity_id>-<sha1[:12]>[-c<chunkIdx>]`。`web-` 前缀让 data_engine 文档与 [`preprocess/raw_sources/demo_corpus.json`](../preprocess/raw_sources/demo_corpus.json) 现有 doc_id 永不冲突；规则在 [`doc_id.py`](doc_id.py)。
- **doc_writer 是落盘的唯一守门人**：[`doc_writer.py`](doc_writer.py) 强制 `license` 字段、强制 `source` 必须以 `web/` 开头、强制 `entity_hint == 目录 entity_id`；同 entity 多份文档合并到同一个 `<entity>.json` 的 `documents` 数组，按 doc_id 去重 + 排序，避免无意义 git diff。
- **HTTP 客户端是唯一外部出口**：[`http_client.py`](http_client.py) 内置令牌桶（`min(global_qps, source.qps)`）+ 指数退避（429/503）+ jitter；所有 source 必须从注入的 `HttpClient` 走。
- **失败不阻塞**：单条 plan 失败计入 `run_report.failed[]`，pipeline 继续；exit code 在 `cli.py` 里依据 `failures` 是否为空决定。
- **断点续抓**：[`cache.py`](cache.py) sqlite 单表记 `(url, status, etag, last_modified, doc_id, fetched_at, error)`，重跑跳过 success URL（默认 168h TTL）；失败超时后才会重试。
- **cache key = 完整 URL**：含 query string。所有共用 base URL 的 source（如 GitHub `search/repositories?q=...`）都必须在 `plan_queries` 阶段把 query params 烘进 URL，否则不同查询会互相覆盖 cache。
- **clean-cache 按 fetcher 自带 hints 精确匹配**：每个 Fetcher 类有 `cache_url_hints`（如 GitHub 的 `("api.github.com",)`）。短名 `gh` 不出现在 URL 里，靠这个属性才能正确清理。新增 source 时务必声明 `cache_url_hints`。
- **长文本切片不切坏句子**：[`normalizer.py`](normalizer.py) 的 `split_long` 在 `max_chars` 边界回溯到最近的句号/换行；切片用 `-c<idx>` 后缀生成稳定 doc_id。
- **wikitext / HTML 清洗保守**：模板（`{{...}}`）、`<ref>`、表格（`{|...|}`）整体丢弃；保留链接显示文本和标题，避免噪声。
- **disambiguation 检测**：英文 "may refer to"、中文 "可以指" 命中即丢弃，避免给一个 entity 灌错义页。

## 与 preprocess 的集成

零侵入：

```bash
python3 -m data_engine run --mode full
python3 -m preprocess          # 既有命令，无任何参数变化
```

[`preprocess/collector.py`](../preprocess/collector.py) 的 `RAW_SOURCE_DIR` 已经用 `rglob("*")` 递归扫所有子目录，`COMMON_COLLECTION_KEYS` 已含 `"documents"`，`_ensure_unique_doc_ids` 会校验 doc_id 唯一性（前缀已天然隔离）。**preprocess 一行代码都不改。**

跑完 `preprocess` 后，下次再跑 `data_engine run --mode incremental` 会读 [`preprocess/output/uncovered_entities.json`](../preprocess/output/uncovered_entities.json) 只针对没覆盖到的节点，提高效率。

## 测试

```bash
python3 -m unittest discover -s data_engine/tests
```

测试矩阵（共 71 个测试）：

- `test_doc_id.py`：命名规则、与 demo_corpus.json 不冲突
- `test_normalizer.py`：HTML / wikitext / disambig / split_long
- `test_targets.py`：query 扩展去重、incremental 软降级
- `test_doc_writer.py`：落盘 schema、按 doc_id 合并、license 强制
- `test_http_client.py`：UA / 重试 / 429 退避 / 节流（mock urlopen，零网络）
- `test_cache.py`：sqlite 缓存 clear() 子串过滤
- `test_sources_roadmap.py`：layer 过滤 + role-name 命中 entity_id
- `test_pipeline_e2e.py`：tmp_path 跑完 → 调 `preprocess.collector` 验证可消费
- `test_struct_writer_and_candidate.py`：roadmap_struct 落盘 + Candidate signature
- `test_proposers.py`：collision 检测、layer 方向、空 corpus 软降级、NodeProposer 永不 auto
- `test_applier.py`：dry-run 不写、apply_batch 原子写入、failure 回滚、rollback 恢复

所有测试都通过依赖注入或 `unittest.mock.patch` 切断网络，**完全离线可跑**。

## 扩展指南（语料抓取层）

- **新增 source**：照 [`sources/wikipedia.py`](sources/wikipedia.py) 复制一份 → 改 `plan_queries` 和 `to_documents` → 在 [`sources/__init__.py`](sources/__init__.py) 加一行 import 触发 `register()`。务必：
  - 从注入的 `http` 走请求，不要自己 `urlopen`；
  - 给 Fetcher 类加 `cache_url_hints = (...)`，否则 `clean-cache --source <你的source>` 没法精确匹配；
  - 如果共用 base URL（如 search 类 API），把 query params 烘进 `FetchPlan.url` 而不是依赖 `params`。
- **新增 entity**：直接在 [`backend/data/seeds/nodes.json`](../backend/data/seeds/nodes.json) 加节点（这步本身需要走仓库的图谱变更流程），data_engine 下次跑会自动接上——`targets.py` 通过 [`preprocess/catalog.py`](../preprocess/catalog.py) 复用同一份目录加载逻辑。
- **新增 license 类型**：直接在新 source 的 `to_documents` 里给 `WebDocument.license` 赋具体值即可；没有许可清单的硬约束，但**禁止留空**——`doc_writer.write_documents` 会拒写。
- **追加查询词扩展**：往 `config.json` 的 `query_expansion.extra_terms` 里加 entity 即可，无须改代码。

## 实测扩充量（语料层 V1+V2）

在当前 34 节点 / 19 别名 key 的图谱、默认 `extra_terms` + GitHub 已认证条件下跑一轮：

| 阶段 | 文档 | mentions | mention≥3 节点 |
| --- | ---: | ---: | ---: |
| 仅 demo_corpus.json | 5 | 91 | 大多 1-3 |
| + wikipedia(en+zh) + roadmap | 36 | 273 | 28/33 |
| + github（带 token） | **431** | **15,449** | **33/33** |

GitHub 是膨胀主力（一份 `awesome-*` README 几 KB 起步、按 8000 字符切片后单个 entity 能贡献几十个 chunk）。如果不打算开 GitHub，仅 wiki+roadmap 也已经能让 mention 涨到 3× 量级。

## 扩图工作流（V3）

V1+V2 的工作只填语料；V3 新增了一套**半自动扩图**流水线，把语料信号转成对 [`backend/data/seeds/`](../backend/data/seeds/) 与 [`backend/data/dictionaries/aliases.json`](../backend/data/dictionaries/aliases.json) 的追加写入。所有写入都会先备份到 [`data_engine/.cache/seed_backups/<timestamp>/`](.cache/seed_backups/)，写完后调 backend 自身的 [`graph_loader`](../backend/app/services/graph_loader.py) + [`graph_quality`](../backend/app/services/graph_quality.py) 校验，**任何失败立刻回滚**。

```bash
# 1. 跑提案：扫 preprocess/output + raw_sources/web/* 生成候选清单
python3 -m data_engine propose
# 输出：data_engine/output/proposals/{aliases,edges,roadmap_edges,nodes}.json
# 同时打印各类型 total / auto_apply_eligible / review_needed

# 2. 看会改什么但不写
python3 -m data_engine apply --dry-run

# 3. 真应用：把所有 auto_apply_eligible=True 的写入 backend seeds（事务式）
python3 -m data_engine apply
# 失败时所有改动从最近备份恢复，不会留下半成品

# 4. 审核需要人工判断的（主要是新节点候选）
python3 -m data_engine review --type nodes
# 交互式 y/n/s/e/q：accept/reject/skip/edit/quit
# 接受的立即落盘并记到 proposals/applied.json；拒绝的进 rejected.json，下次不再问

# 5. 校验图谱
python3 -m backend.app.main validate-graph

# 出问题时手动回滚
python3 -m data_engine list-backups
python3 -m data_engine rollback --to 20260518T080501Z
```

四个 proposer：

| proposer | kind | 信号源 | 默认自动应用条件 |
| --- | --- | --- | --- |
| [`AliasProposer`](proposers/aliases.py) | alias | `preprocess/output/mentions.json` 的 surface 变体 | avg_conf ≥ 0.85 AND doc_count ≥ 3 AND 不在 `alias_ambiguity` near-tie 集合 AND 无 cross-entity collision |
| [`CooccurrenceEdgeProposer`](proposers/edges_cooccurrence.py) | edge | `document_entities.json` 共现矩阵 | cooc ≥ 30 AND layer 方向合规（低层 → 高层） |
| [`RoadmapEdgeProposer`](proposers/edges_roadmap.py) | edge | `data_engine/output/roadmap_struct/<role>.json` 的 react-flow JSON | layer 方向合规（roadmap.sh 信号最干净，全部 auto） |
| [`NodeProposer`](proposers/nodes.py) | node | `raw_sources/web/gh/*.json` 的 README token TF（启发式过滤 stopwords / URL 片段 / 用户名） | **永不 auto**——layer 归属是语义判断，必须 review |

阈值在 [`config.json`](config.json) 的 `proposers` 节统一调。降低阈值会扩大候选集但增加 review 成本。

### V3-V5 实测扩图（基于当前 34 节点起点）

| 阶段 | nodes | edges | alias keys | 总别名 | mentions |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 末尾（手工权威源） | 34 | 56 | 19 | 68 | 91 |
| `apply --auto`（仅别名 + 共现边） | 34 | 98 (+42) | 34 (+15) | 129 (+61) | — |
| V3 curated batch（10 evidence 节点 + supports 边） | 44 (+10) | 108 (+10) | 34 | 129 | 15,449 |
| V4 curated batch（再 10 evidence 节点 + 边 + 别名） | 54 (+10) | 118 (+10) | 54 (+20) | 170 (+41) | — |
| **V5 五层平衡扩图**（97 节点跨 5 层 + 127 边 + 190 别名） | **151** (+97) | **328** (+210) | **151** (+97) | **361** (+191) | **126,907** |

V5 把图谱从只有 4 个 role（backend/data/ml/frontend engineer）扩到 10 个——新加了 DevOps engineer、SRE、移动开发、安全、全栈、AI engineer 6 条职业线，每条都从 evidence → ability → composite → direction → role 完整连通。layer 分布：evidence 109 / ability 15 / composite 8 / direction 9 / role 10（金字塔保持）。

V3+V4+V5 curated 批次都走 `applier.apply_batch(node_cands, edge_cands, alias_cands)` —— 节点 / 边 / 别名一次性原子写入，**绕开 NodeProposer 的 review 通道直接落地**。适合"我已经知道这批要加什么"的场景，把 layer 归属判断前置到 plan / 脚本里完成。详见下面"批量扩图 (`apply_batch`)"。

V5 的具体 ID 列表与边布线代码见 [`data_engine/scripts/v5_balanced_batch.py`](scripts/v5_balanced_batch.py)，可作为后续大批量扩图的模板。

### 批量扩图（`apply_batch`）

[`applier.apply_batch`](applier.py) 是 V3 加的混合批量入口，解决了"加 evidence 节点时缺出边校验失败"的死锁——单独调 `apply_nodes` 会因为新 evidence 节点没有出边被 [`graph_quality`](../backend/app/services/graph_quality.py) 判 `evidence 不能影响任何非 evidence 节点` 直接回滚。`apply_batch` 在校验前一次性写完节点 + 边 + 别名，校验失败时三个文件一起恢复。

最小调用：

```python
from data_engine import applier
from data_engine.proposers.candidate import Candidate

nodes = [Candidate(kind="node",
                   payload={"id": "redis", "label": "Redis", "layer": "evidence",
                            "aggregator": "source", "cap": 1.0},
                   confidence=1.0, auto_apply_eligible=True, source_proposer="curated")]
edges = [Candidate(kind="edge",
                   payload={"source": "redis", "target": "database_practice",
                            "relation": "supports", "weight": 0.7},
                   confidence=1.0, auto_apply_eligible=True, source_proposer="curated")]
aliases = [Candidate(kind="alias",
                     payload={"entity_id": "redis", "alias": "缓存"},
                     confidence=1.0, auto_apply_eligible=True, source_proposer="curated")]

applier.apply_batch(nodes, edges, aliases)
# 失败会从 data_engine/.cache/seed_backups/<ts>/ 自动恢复
```

V3+V4 的 20 个 curated 节点走的就是这条路；rollback 用 `python3 -m data_engine rollback --to <timestamp>`。

### 离线网络图（`viz`）

前端的"图谱传播"页是 5 列卡片堆叠（每层一列、显示分数 bar），不是网络图、且需要先提交 evidence 才有数据。要看**当前 seeds 完整结构**（44+ 节点的连接关系、按 layer 分布、新增节点高亮），用：

```bash
python3 -m data_engine viz
# 输出：data_engine/output/graph_view.html
```

[`viz.py`](viz.py) 渲染一份纯 SVG 自包含网页（无 JS、无 CDN、无外部依赖），5 层从左到右排开，节点之间画弧线，按 relation 上色（supports 灰、requires 红、prefers 绿、evidences 蓝、inhibits 橙），data_engine 引入的节点用金色标出。

WSL 上用 Windows 浏览器看时，因为 `file://` 协议跨 WSL/Windows 边界经常打不开，起一个本地 http server：

```bash
cd data_engine/output && python3 -m http.server 8181 --bind 127.0.0.1
# Windows Chrome 打 http://127.0.0.1:8181/graph_view.html
```

### V3 设计要点

- **append-only**：proposers/applier 永不删改原条目。`backend/data/seeds/` 里手工权威条目和 V3 追加条目混存，靠"已有则跳过"识别；rollback 通过备份目录回到任意历史状态。
- **每个候选带 signature**：`alias::<entity>::<text>` / `edge::<src>::<rel>::<tgt>` / `node::<id>`。`proposals/applied.json` 与 `proposals/rejected.json` 记录这些 signature 当黑/白名单，重复 propose 不会再灌相同候选给你。
- **roadmap 双轨**：[`sources/roadmap.py`](sources/roadmap.py) fetch 时既写一份纯文本到 `web/roadmap/<entity>.json` 给 preprocess，又写一份原始 react-flow JSON 到 [`data_engine/output/roadmap_struct/<role>.json`](output/roadmap_struct/) 给 RoadmapEdgeProposer。后者目前 0 候选，因为大多 roadmap 节点（git/javascript/k8s 等）还不是图谱节点；`review --type nodes` 接受这些后下一轮 propose 才会出 roadmap edge。
- **applier in-process 校验**：写盘后调用 backend 自身的 [`graph_loader.load_graph_data`](../backend/app/services/graph_loader.py) + [`graph_quality.validate_graph_quality`](../backend/app/services/graph_quality.py)；任何 GraphValidationError 触发回滚。等同于命令行 `validate-graph` 但跑在同一进程，不需要 subprocess。

### 扩图相关测试

新增的测试文件：

- `tests/test_struct_writer_and_candidate.py`：roadmap_struct 落盘 + Candidate signature
- `tests/test_proposers.py`：collision 检测、layer 方向、空 corpus 软降级、NodeProposer 永不 auto
- `tests/test_applier.py`：dry-run 不写、failure 回滚、rollback 恢复（用 monkey-patched seed paths）

跑全部：

```bash
python3 -m unittest discover -s data_engine/tests
```
