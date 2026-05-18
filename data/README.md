# data 目录说明

本文件记录 **KG 实体扩展与实体链接** 相关改动，便于后续合并进主图或继续评审。  
运行时推荐后端仍只读取 `seeds/nodes.json` 与 `seeds/edges.json`（365 节点 / 约千条边），**未自动切换** 到扩展产物。

---

## 一、本次新增内容概览

| 类型 | 路径 | 作用 |
| --- | --- | --- |
| 构建脚本 | `scripts/build_entity_pairs.py` | 跨分支实体配对 + 与现有 KG 的链接候选 |
| 构建脚本 | `scripts/build_entity_expansion_nodes.py` | 398 节点、五层结构（仿 `seeds/nodes.json`） |
| 构建脚本 | `scripts/build_entity_pairwise_relations.py` | 398 节点两两全连接边（仿 `seeds/edges.json`） |
| 实体链接产物 | `entity_expansion/entity_expansion_candidates.json` | 分支实体 → 现有 KG / 新实体候选 |
| 跨分支配对 | `entity_linking_pairs/entity_pairs.json` | feat/data-engine ↔ entityRepo 配对表 |
| 扩展节点 | `entity_expansion/entity_expansion_nodes.json` | 398 节点定义 |
| 扩展边 | `entity_expansion/entity_expansion_pairwise_edges.json` | 79,003 条两两边 |
| 说明文档 | `entity_expansion/README.md`、`entity_linking_pairs/README.md` | 子目录细节 |

**未改动的核心运行时数据**：`seeds/nodes.json`、`seeds/edges.json`、`runtime/` 等保持原状。

---

## 二、实体链接：怎么提取的

### 命令

```bash
python3 data/scripts/build_entity_pairs.py
```

### 输入（通过 `git show <ref>:<path>` 读取，无需 checkout 分支）

| 来源 | 引用 | 主要路径 |
| --- | --- | --- |
| 现有 KG | `main` | `data/seeds/nodes.json`、`data/sources/skills.json`、别名词典等 |
| 运行时图 | `feat/data-engine` | `backend/data/seeds/nodes.json` |
| 实体仓库 | `entityRepo` | `optimize/output/skills_enriched.json` |

### 匹配方法

1. 对 `id`、`label`、`aliases` 做归一化（NFKC、小写、compact key）。
2. 用 surface key 倒排索引找候选匹配。
3. 按 id 命中、label 命中组合计算 `confidence`（约 0.75–0.98）。
4. **链接判定**：
   - `>= 0.9` → `auto_link`（写入 `linked_to_existing`）
   - `0.75 – 0.9` → `review_link`（需人工确认）
   - `< 0.75` 或无匹配 → 进入 `new_entity_candidates`

### 输出与规模（`entity_expansion_candidates.json`）

| 字段 / 统计 | 数量 |
| --- | ---: |
| 现有 KG 实体 | 365 |
| 分支候选记录合计 | 227 |
| 已链接到现有 KG | 194（其中 auto 191，review 3） |
| 未链接、建议新增 | 33 |
| 若全部接纳新实体后总规模 | **398** |

另生成：`entity_linking_pairs/entity_pairs.json`（两分支之间的配对列表）。

---

## 三、扩展节点：398 个、五层分类

### 命令

```bash
python3 data/scripts/build_entity_expansion_nodes.py
```

### 实体组成

- **365**：原样来自 `seeds/nodes.json`
- **33**：来自 `entity_expansion_candidates.json` 的 `new_entity_candidates`（LLM/工具/能力等待审条目）

### 五层（与 README / 运行时一致）

| layer | 数量 | 含义 |
| --- | ---: | --- |
| `evidence` | 187 | 技能、工具、知识、项目、兴趣、约束等 |
| `ability` | 84 | 基础能力单元 |
| `composite` | 63 | 复合能力 |
| `direction` | 14 | 岗位方向 |
| `role` | 50 | 具体职业 |

### 产物

| 文件 | 说明 |
| --- | --- |
| `entity_expansion/entity_expansion_nodes.json` | 与 `seeds/nodes.json` 同 schema 的节点数组 |
| `entity_expansion/entity_expansion_nodes.summary.json` | 分层统计 |

新节点 `metadata.origin` 为 `entity_expansion`，并保留 `aliases`、`source_records` 等评审信息。

---

## 四、扩展边：两两全连接 + 四种关系

### 命令

```bash
python3 data/scripts/build_entity_pairwise_relations.py
```

### 关系类型（仅四种）

将原图中的 `supports`、`evidences` **统一为** `support`：

| 关系 | 说明 |
| --- | --- |
| `support` | 正向支撑（含原 supports / evidences） |
| `requires` | 关键前置 |
| `prefers` | 偏好加成 |
| `inhibits` | 抑制 |

### 边如何生成

1. **优先复用主图**：若 `seeds/edges.json` 中已有两端点边，保留其 `weight`、`note`，仅把关系名归一为 `support`（原 `supports`/`evidences`）。
2. **其余点对**：按层级与类别启发式补全（constraint→inhibits、interest→prefers、knowledge→requires、低层→高层→support 等）。

### 规模（`entity_expansion_pairwise_edges.summary.json`）

| 指标 | 数量 |
| --- | ---: |
| 实体 | 398 |
| 边（无序对，每对一条有向边） | 79,003 |
| 来自 seeds | 937 |
| 启发式补全 | 78,066 |

### 产物格式

与 `seeds/edges.json` 一致：`source`、`target`、`relation`、`weight`、`note`、`metadata`。

> **注意**：主图推理代码（`backend/app/services/inference_engine.py`）当前识别的是 **`supports` / `evidences`**（复数），扩展边文件使用 **`support`**（单数）。直接替换 seeds 前需统一命名或改推理层。

---

## 五、目录结构（与本改动相关）

```text
data/
├── README.md                          # 本文件
├── scripts/
│   ├── build_entity_pairs.py          # 实体链接 + 候选清单
│   ├── build_entity_expansion_nodes.py
│   └── build_entity_pairwise_relations.py
├── entity_expansion/
│   ├── README.md
│   ├── entity_expansion_candidates.json
│   ├── entity_expansion_nodes.json
│   ├── entity_expansion_nodes.summary.json
│   ├── entity_expansion_pairwise_edges.json      # ~30MB
│   └── entity_expansion_pairwise_edges.summary.json
├── entity_linking_pairs/
│   ├── README.md
│   └── entity_pairs.json

```

其余目录（`sources/`、`dictionaries/`、`canonical/`、`runtime/`、`demo/` 等）为原有图谱与评测数据，**本次未修改**。

---

## 六、能否直接并入运行时图？

| 产物 | 可否直接合并 | 说明 |
| --- | --- | --- |
| `entity_expansion_candidates.json` | 部分 | 194 条已映射；33 条新实体需审核后写入 `sources/` 并重新编译 seeds |
| `entity_expansion_nodes.json` | 需流程 | 需合并进 `seeds/nodes.json` 或重建 seeds 后后端才加载 |
| `entity_expansion_pairwise_edges.json` | **不建议整包** | 全连接图会破坏 DAG 语义与推理；仅宜挑选种子边或人工策展边入库 |

`GraphLoader` 固定路径：


