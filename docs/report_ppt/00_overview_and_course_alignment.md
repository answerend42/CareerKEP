# 总览：CareerKEP 的知识图谱扩容与推理链路

## 一句话概括

CareerKEP 做的是一个面向计算机职业推荐的领域知识图谱系统。我们把用户输入中的技能、项目、兴趣、约束映射成图谱节点，再沿图谱关系传播，最终推荐合适的职业角色，并给出原因、差距和行动建议。

从课程角度看，这个项目不是单点算法，而是一条较完整的知识工程流程：

```text
数据获取 -> 清洗与预处理 -> 实体识别 -> 实体消歧/链接
       -> 知识体系构建 -> 关系抽取/关系规划 -> 图谱存储与展示
       -> 知识推理 -> 推荐解释与行动模拟
```

## 课程知识点对齐

| 课件章节 | 老师课件中的核心概念 | 项目里的对应内容 |
| --- | --- | --- |
| 课程概述 | 从数据到知识，从系统到知识系统、智能系统 | 把简历/JD/公开语料转为职业知识图谱，并用它做推荐系统 |
| 第 1 章 概述 | 数据、信息、知识；知识库；知识图谱生命周期 | CareerKEP 从原始文本和 seed 图谱构建可推理知识库 |
| 第 2 章 知识表示 | 语义网络、RDF/三元组、知识表示作为推理媒介 | 节点 + 有向标签边表示职业领域事实，边关系承担推理语义 |
| 第 3 章 知识体系构建与知识融合 | Knowledge Schema、本体、分类体系、知识融合 | 五层节点体系、四类关系体系、多个分支产物融合 |
| 第 4 章 实体识别和扩展 | 知识获取、信息抽取、命名实体识别、细粒度实体分类 | 从 JD/简历/网页语料中抽取技能、工具、项目、岗位等实体 |
| 第 5 章 实体消歧 | name variation、name ambiguity、实体链接 | 别名词典、候选实体聚类、crosswalk、review queue |
| 第 6 章 关系抽取 | 从实体对识别有序关系，形成三元组 | DeepSeek 判断节点对关系，输出 `source-relation-target` |
| 第 8 章 存储与检索 | RDF 三元组、图模型、属性图模型 | JSON 图谱 bundle、overview HTML、后端图加载器 |
| 第 9 章 知识推理 | 从已知事实推断未知知识；推理引擎 + 知识库 | DAG 拓扑传播、core/aux 双通道、formal/near miss/bridge |

## 我们的知识体系

### 五层节点

这五层是项目中的领域 Knowledge Schema。它对应课件第 3 章中“知识体系是知识数据的元数据和概念框架”的概念。

| 层级 | 含义 | 例子 | 在推理里的作用 |
| --- | --- | --- | --- |
| `evidence` | 用户输入或语料中可直接观察到的原子证据 | Python、Docker、RAG、后端项目、不擅长 C++ | 作为根证据输入 |
| `ability` | 由多个 evidence 支撑出的基础能力 | 后端技术栈、数据库实践、沟通能力 | 把零散技能归纳成能力 |
| `composite` | 多个 ability 组合出的复合能力 | Web 开发能力、数据工程能力、机器学习应用能力 | 接近岗位能力画像 |
| `direction` | 职业方向 | 后端方向、数据方向、算法方向 | 做方向级推荐和 bridge |
| `role` | 具体岗位 | 后端工程师、NLP 工程师、MLOps 工程师 | 正式推荐排序目标 |

### 四类关系

项目最终只保留四类关系。历史上的 `evidences` 已经合并进 `supports`，这样前端图例、后端计算和报告术语都更统一。

| 关系 | 含义 | 示例 |
| --- | --- | --- |
| `supports` | A 正向支撑 B，表示 A 会提高 B 的成立或匹配程度 | `Python -> 后端技术栈` |
| `requires` | B 需要 A 作为关键前置，表示缺少 A 时 B 的成立会明显变弱 | `数据结构 -> 算法能力` |
| `prefers` | A 是偏好或倾向，会提高 B 的适配度，但不是硬要求 | `偏好数据分析 -> 数据方向` |
| `inhibits` | A 是约束、短板或反偏好，会抑制 B | `不喜欢值班 -> 运维方向` |

## 各小组工作在生命周期中的位置

| 小组 | 主要贡献 | 生命周期位置 | 对最终图谱的价值 |
| --- | --- | --- | --- |
| ztt & qyw | 数据获取 + 清洗，主要是 entityRepo 实体仓库 | 知识获取、实体识别、实体消歧、实体链接 | 提供更多实体、别名、mention、外部标准引用和关系候选材料 |
| lsy & ljc | seed 方法的图谱扩容，`data_engine` 工具链 | 基于已有图谱的实体扩展、关系候选生成、图谱增量落盘 | 从 seed 节点出发抓公开语料，自动生成候选节点/别名/边并支持回滚 |
| sx & wxs | 关系设计与 DeepSeek 关系规划 | 知识体系、关系抽取、三元组构建、质量控制 | 把 398 个节点转成可审阅扩展图谱，保留 2,342 条非 very-low LLM 边 |
| jrh & syg | 后端推理方法 + 输入处理 | 知识推理、实体链接应用、推荐解释 | 把扩展图谱用于推荐，同时用 core/aux 双通道控制 LLM 边风险 |

## 当前最终产物

最终 main 里可以用于汇报和演示的关键产物：

| 产物 | 作用 |
| --- | --- |
| `data/seeds/nodes.json`、`data/seeds/edges.json` | 原始 seed 图谱，365 节点、1,053 边 |
| `data/entity_expansion/entity_expansion_nodes.json` | 398 节点实体列表，365 原节点 + 33 新节点 |
| `data/entity_expansion/llm_expanded_graph.clean.json` | 清洗后的 398 节点、3,395 边全量审阅图 |
| `data/entity_expansion/llm_edge_judgments.accepted.json` | DeepSeek 非 `none` 关系判断结果 |
| `frontend/public/kg-expanded-clean-overview.html` | 扩展图谱可视化 |
| `backend/app/services/graph_loader.py` | 把边编译为 `core/aux/similarity/explain` 通道 |
| `backend/app/services/inference_engine.py` | 图上传播推理与双通道分数计算 |
| `backend/app/api/recommend.py` | formal、near miss、bridge 推荐编排 |

## 报告中最重要的主线

建议 PPT 不要按 Git 分支顺序讲，而按知识工程流程讲：

1. 先讲我们定义了职业知识图谱的 schema：五层节点、四类边。
2. 再讲实体从哪里来：entityRepo 做数据获取、清洗、NER、消歧；data_engine 做从 seed 出发的公开语料扩容。
3. 再讲关系怎么来：SX 设计候选边和 DeepSeek 关系判断，不把 79,003 条全连接边直接入库。
4. 最后讲怎么用：后端把图谱分成 core/aux 通道，LLM 边帮助发现候选，但正式推荐必须由 core 证据支撑。

这样能体现课件里的完整链路：数据不是直接变推荐，而是先变成有结构、有语义、有质量控制的知识，再由推理引擎使用。
