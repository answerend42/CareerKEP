# lsy & ljc：基于 seed 方法的图谱扩容

对应分支：`feat/data-engine`
主要目录：`data_engine/`

## 一句话定位

这个分支负责从已有 seed 图谱出发，自动抓取公开语料，再根据 mention、共现、roadmap 结构和规则生成新节点、新别名和新边候选。它是“以原图谱为中心向外扩”的扩容方法。

和 `entityRepo` 的区别是：

- `entityRepo` 更像“从外部数据构建实体仓库”。
- `data_engine` 更像“从已有图谱出发，围绕 seed 节点扩展图谱”。

## 与课件知识点的对应

| 课件知识点 | 分支里的实现 |
| --- | --- |
| 第 1 章：知识图谱生命周期 | 形成可重复执行的采集、抽取、候选、审核、入图流程 |
| 第 3 章：知识体系 / Schema | 所有扩展都要符合原有五层节点体系和关系约束 |
| 第 4 章：实体扩展 | 从公开语料中发现新技术词、工具词、别名 |
| 第 6 章：关系抽取 | 根据共现、roadmap 结构、关键词规则生成关系候选 |
| 第 8 章：存储与检索 | 输出 graph manifest、graph contract、overview/viz 等机器可读产物 |

## 核心方法：从 seed 图谱出发

`data_engine` 的扩容思路是：

```text
已有图谱节点 + 已有别名
        -> 生成查询目标
        -> 抓取公开语料
        -> 交给 preprocess 抽取 mention
        -> 生成 alias/node/edge proposals
        -> 自动或人工审核
        -> 事务式写入 seeds
```

这是一种“seed-based expansion”。它不会凭空全网挖实体，而是围绕已有节点扩展，所以更容易保持领域边界和图谱 schema 的一致性。

## 处理流水线

### Step 1：语料抓取

相关代码：

- `data_engine/corpus/targets.py`
- `data_engine/corpus/sources/github.py`
- `data_engine/corpus/sources/roadmap.py`
- `data_engine/corpus/sources/wikipedia.py`
- `data_engine/corpus/sources/onet.py`
- `data_engine/corpus/http_client.py`
- `data_engine/corpus/cache.py`
- `data_engine/corpus/doc_writer.py`

抓取来源：

| 来源 | 作用 |
| --- | --- |
| GitHub | 从 README 和项目描述中发现技术工具、框架、实践词 |
| roadmap.sh | 获取职业/技术路线结构，适合生成 prerequisite/supports 类候选边 |
| Wikipedia | 提供较稳定的百科解释和别名表述 |
| O*NET | 提供职业能力结构和外部职业标准线索 |

这个阶段只写语料，不直接改图谱。

### Step 2：复用 preprocess

`data_engine` 会把抓回来的语料写成已有 `preprocess` 能读的格式：

```text
preprocess/raw_sources/web/<source>/<entity>.json
```

然后复用项目原有的：

```bash
python3 -m preprocess
```

这体现了工程上的一个优点：新模块和原有抽取管线通过数据契约连接，而不是重写一套文本处理流程。

### Step 3：生成候选

相关代码：

- `data_engine/proposers/aliases.py`
- `data_engine/proposers/edges_cooccurrence.py`
- `data_engine/proposers/edges_roadmap.py`
- `data_engine/proposers/nodes.py`
- `data_engine/proposers/nodes_auto/`

候选类型：

| Proposer | 输入 | 输出 | 用途 |
| --- | --- | --- | --- |
| `aliases` | mentions | alias candidates | 扩展实体链接词典 |
| `edges_cooccurrence` | document_entities | cooccurrence edges | 从文档共现召回关系候选 |
| `edges_roadmap` | roadmap 结构 | roadmap edges | 从路线图结构生成方向更明确的关系候选 |
| `nodes` | GitHub 语料高频词 | node candidates | 发现新 evidence 节点 |
| `nodes_auto` | 规则 + 共现索引 | node packages | 半自动生成 evidence 节点及其父边 |

### Step 4：审核与入图

相关代码：

- `data_engine/graph/applier.py`
- `data_engine/graph/packages.py`
- `data_engine/graph/review.py`
- `data_engine/core/package.py`

关键设计：

- 写入前先备份 seeds。
- 写入后立刻做图谱质量校验。
- 校验失败自动回滚。
- `NodePackage` 把新节点、必选边、别名绑定为一个事务单元，避免出现“孤立节点”。

这部分可以对应课件里的“知识库构建工程方法”和“知识质量控制”。

### Step 5：图谱契约与可视化

相关文档和产物：

- `data/docs/graph_contract.md`
- `data/docs/relation_candidates.md`
- `data_engine/graph/viz.py`
- `data_engine/output/graph_view.html`

`graph_contract.json` 的思想是把后端需要消费的关系类型、权重规则、构图健康度和输出文件集中成一个机器可读契约，减少后端分散依赖。

## 主要图谱贡献

该分支经历了多个扩图阶段：

| 阶段 | 图谱规模 | 说明 |
| --- | --- | --- |
| 早期 `data_engine` 扩图 | 34 -> 54 nodes，56 -> 118 edges | 通过 web corpus 挖出 20 个 evidence 节点 |
| V5 balanced expansion | 54 -> 151 nodes，118 -> 328 edges | 扩展到更完整的五层图谱 |
| alias 扩展 | 170 -> 361 alias entries | 提升实体链接召回 |
| mention 扩展 | 91 -> 126,907 mentions | 公开语料带来大量 mention 证据 |

早期直接新增的 20 个 evidence 节点包括：

| 节点 | 说明 |
| --- | --- |
| PyTorch、TensorFlow、BERT、Transformer、NLP、spaCy | 机器学习/NLP 技术栈 |
| GPT、LLM、Hugging Face、LangChain、Prompt Engineering、Fine-tuning、RAG、LLaMA | 大模型应用相关实体 |
| MongoDB、Redis、Kubernetes、FastAPI、Git、Java | 后端与工程技术栈 |

这些实体后来也为 SX 的 398 节点扩展和后端 LLM/RAG/NLP 演示提供了输入基础。

## 对实体链接和关系预测的价值

`data_engine` 给后续工作提供了三类输入：

1. 标准节点 ID：新增 evidence 节点已经带有 layer、node_type、aggregator 和父级边。
2. 别名词典：大幅增加实体链接可命中的 surface。
3. 语料证据：GitHub、roadmap、Wikipedia 文档可重新跑 preprocess，得到 mention 和共现矩阵。

这对实体链接尤其重要，因为用户可能不会输入标准节点名：

```text
用户输入：大模型 / langchain / 检索增强 / k8s / torch
          -> alias dictionary
          -> LLM / LangChain / RAG / Kubernetes / PyTorch
```

## 为什么这是 seed 方法

这个方法的关键不是“抓了很多数据”，而是“从已有图谱节点出发抓数据”。它有三个好处：

1. 领域边界清楚：不会把无关实体大量引入职业推荐图谱。
2. 和原 schema 一致：新节点必须落在 evidence/ability/composite/direction/role 体系中。
3. 可控可回滚：每次扩图都有 proposals、review、backup、validate、rollback。

## PPT 可讲重点

可以用下面的话概括：

> lsy & ljc 做的是基于 seed 的自动扩图。系统先用已有节点和别名生成查询目标，再从 GitHub、roadmap、Wikipedia、O*NET 抓公开语料，经过 preprocess 得到 mention 和共现信号，最后生成别名、节点和边候选。入图时通过 NodePackage、质量校验和回滚机制保证不会破坏原图谱。

适合展示的流程图：

```text
seed nodes/aliases
      -> public corpus fetching
      -> preprocess mentions
      -> alias/node/edge proposers
      -> proposals
      -> review/apply/rollback
      -> expanded seeds + graph contract + visualization
```
