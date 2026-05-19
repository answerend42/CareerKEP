# jrh & syg：后端推理方法与输入处理

主要目录：

- `backend/app/services/`
- `backend/app/api/recommend.py`
- `frontend/src/app/`

## 一句话定位

这部分负责把知识图谱真正用起来：把用户自然语言或结构化输入归一为标准图谱节点，在图上进行分数传播，最后输出正式推荐、near miss、bridge、路径解释、差距分析和行动模拟。

用课程术语说，它主要对应：

```text
实体链接应用 -> 知识推理 -> 推荐解释 -> 知识系统应用
```

## 与课件知识点的对应

| 课件知识点 | 后端里的实现 |
| --- | --- |
| 第 2 章：知识表示作为推理媒介 | 图谱节点和边被编译为可计算的 runtime graph |
| 第 5 章：实体链接 | 用户输入通过 alias dictionary 映射到标准节点 ID |
| 第 8 章：图数据模型 | 后端把 JSON 图谱加载成 incoming/outgoing/topological_order |
| 第 9 章：知识推理 | 沿 DAG 拓扑序传播分数，从 evidence 推到 role |
| 第 9 章：推理引擎 + 知识库 | `InferenceEngine` 是推理引擎，KG 是知识库 |

## 输入处理

系统支持两类输入：

1. 自然语言输入，例如“我会 Python、Java、Spring Boot，喜欢后端”。
2. 结构化输入，例如前端滑杆或 API 里的 `signals`。

两类输入最终都会归一成同一种形式：

```text
node_id -> score
```

汇报时如果说“结构化输入转非结构化输入”，建议进一步解释为：系统同时支持非结构化文本和结构化信号，但后端真正做的是把两类输入都统一成结构化的图谱节点分数。这样和课件第 5 章“实体链接”的说法更一致。

相关代码：

- `backend/app/services/nl_parser.py`
- `backend/app/services/input_normalizer.py`
- `data/dictionaries/skill_aliases.json`
- `data/dictionaries/parsing_patterns.json`
- `data/dictionaries/preference_patterns.json`

### 自然语言解析

`LightweightNLParser` 做三件事：

1. 按中文/英文标点切分片段。
2. 用 alias pattern 匹配技能、工具、知识点、项目等 evidence。
3. 用 phrase rules 识别偏好、约束、强弱程度和负向表达。

例如：

```text
我会 Python Java Spring Boot MySQL，喜欢后端
```

会被转成类似：

```text
skill_python -> 0.62
skill_java -> 0.62
tool_spring_boot -> 0.62
tool_mysql -> 0.62
interest_backend -> 0.86
```

### 结构化输入归一

`InputNormalizer` 负责把 API 或前端传来的 `entity + score` 映射到标准节点：

```text
entity surface -> alias_index -> node_id -> NormalizedSignal
```

如果用户输入 `LLM`、`大模型`、`LangChain`，只要 alias dictionary 中存在对应关系，就可以链接到标准节点。

## 图谱加载与边策略

相关代码：

- `backend/app/services/graph_loader.py`

旧系统只有一个 runtime graph。扩展图谱加入大量 LLM 边后，如果所有边都等价进入传播器，单个通用技能可能激活大量岗位。因此当前 main 把边分成四个通道：

| 通道 | 含义 | 是否参与正式推荐 |
| --- | --- | --- |
| `core` | seed/curated 正式评分骨架 | 是 |
| `aux` | LLM 辅助语义信号 | 参与辅助分，但不能开 formal gate |
| `similarity` | 同层相似或相关关系 | 不进正式传播，用于候选和审阅 |
| `explain` | 只解释或待审风险边 | 不进正式传播 |

关系语义仍然是：

```text
supports / requires / prefers / inhibits
```

但每条边还会被加上评分策略：

```text
scoring_policy
provenance
trust
eligible_for_gate
eligible_for_formal_score
```

核心原则：

```text
LLM 边可以帮助发现方向
但默认不能让岗位直接进入正式推荐
```

## 推理算法

相关代码：

- `backend/app/services/inference_engine.py`

图谱是五层 DAG：

```text
evidence -> ability -> composite -> direction -> role
```

推理按拓扑序运行。每个节点都有一个 `NodeState`：

| 字段 | 含义 |
| --- | --- |
| `score` | 最终展示分数 |
| `core_score` | 只来自 core 通道，用于正式推荐资格 |
| `aux_score` | 来自 LLM 辅助通道，有严格上限 |
| `formal_eligible` | role 是否能进入正式推荐 |
| `evidence` | 哪些根证据贡献了分数 |
| `parent_contributions` | 父节点通过边传来的贡献 |
| `diagnostics` | 支持、要求、偏好、抑制等分量 |

### 父边贡献

每条边的贡献：

```text
contribution = parent_score * edge_weight * relation_factor * edge_trust
```

其中：

- `supports` factor = 1.0
- `requires` factor = 1.0
- `prefers` factor = 0.75
- `inhibits` factor = 1.0
- LLM 未审阅边 trust = 0.15

### 根证据去重

同一个根证据可能通过多条路径到达一个岗位。为了避免路径越多分数越高，系统用 noisy-or 聚合：

```text
noisy_or(xs) = 1 - Π(1 - x_i)
```

含义是：多条弱路径可以共同增强，但不会无限叠加。

### core 分和 aux 分

core 分用于正式推荐：

```text
core_base_positive =
  supports
  + requires * 0.65
  + prefers
  + direct_input
```

aux 分用于候选发现：

```text
aux_score =
  min(aux_cap, aux_support + aux_require * 0.55 + aux_prefer * 0.45)
```

aux 上限：

| 节点类型 | aux cap |
| --- | ---: |
| role | 0.08 |
| 非 role | 0.12 |

最终展示分：

```text
score = core_score + aux_score
```

正式推荐资格：

```text
formal_eligible = role.core_score >= 0.05
```

所以 `aux_score` 可以让岗位出现在 near miss 或 bridge，但不能让岗位直接进入 formal recommendation。

## 专项岗位锚点

相关代码：

- `backend/app/api/recommend.py`
- `_role_needs_specialized_anchor`
- `_specialized_anchor_signal`

问题：

```text
Python + Java + Spring Boot + MySQL + 后端偏好
```

这说明用户适合后端方向，但不能说明用户适合 Rust 服务工程师。

因此系统对专项岗位加锚点门槛。专项岗位包括：

```text
Rust 服务工程师
React 前端工程师
NLP 工程师
大模型应用工程师
MLOps 工程师
```

实现逻辑：

1. 如果 role 的 `metadata.role_kind == specialization`，需要专项锚点。
2. 如果 role id/name 中含有 `python/java/rust/react/vue/nlp/llm/mlops` 等技术 token，也需要锚点。
3. 锚点来自用户直接输入或 core evidence。
4. 锚点分数必须达到 `0.12`。

这不是维护一个“岗位 gate 表”，而是根据 role metadata 和 role id/name token 动态判断。

## 推荐输出编排

相关代码：

- `backend/app/api/recommend.py`
- `backend/app/services/explainer.py`
- `backend/app/services/role_gap_analyzer.py`
- `backend/app/services/learning_path_planner.py`
- `backend/app/services/action_simulator.py`

输出分三层：

| 输出 | 条件 | 作用 |
| --- | --- | --- |
| formal recommendations | core 分和专项锚点达标 | 正式推荐岗位 |
| near miss | 有一定相关性但门槛不足 | 告诉用户“接近但还差什么” |
| bridge recommendations | 输入太少或只有方向信号 | 给出方向和下一步补齐路径 |

这让系统更像职业规划助手，而不是“看到一个词就下岗位结论”。

## 前端对应修改

前端也配合了图谱和推理变化：

- 图例从五类边改成四类边，去掉单独的 `evidences`。
- 传播节点和详情中展示 `core_score`、`aux_score`、`formal_eligible` 等诊断信息。
- 图谱 overview 使用扩展后的清洗 KG 数据。
- `kg-expanded-clean-overview.html` 展示 398 节点、3,395 边的图谱。

## 演示案例

### 案例 1：后端画像不会乱推 Rust

输入：

```text
我会 Python Java Spring Boot MySQL 喜欢后端
```

预期讲法：

- 系统能正式推荐 Java/通用后端。
- Rust 服务工程师可能出现在 near miss。
- 因为没有 Rust 锚点，所以 Rust 不进入 formal。

### 案例 2：有 Rust 锚点才推荐 Rust

输入：

```text
我会 Rust Linux 做过低延迟服务项目 喜欢后端
```

预期讲法：

- Rust 是明确专项证据。
- Rust 服务工程师可以进入 formal。
- 这说明系统不是简单压低 Rust 权重，而是要求专项岗位有专项证据。

### 案例 3：LLM 作为方向信号

结构化输入：

```json
{"signals":[{"entity":"LLM","score":0.9}],"top_k":5}
```

预期讲法：

- LLM 可以激活大模型/NLP/AI 应用方向。
- 但如果缺少 Python、RAG 项目、工程能力等 core 证据，不应该直接 formal 推荐“大模型应用工程师”。
- 这体现了 aux 通道的作用：发现可能性，而不是正式下结论。

## PPT 可讲重点

可以用下面的话概括：

> jrh & syg 做的是图谱推理和输入处理。用户输入先通过别名和规则归一到标准节点，然后在五层 DAG 上做分数传播。扩展图谱加入 LLM 边后，后端把边分成 core 和 aux：core 负责正式推荐，aux 只负责候选发现和 near miss。这样既能利用扩展图谱，又不会让 LLM 边直接把岗位推成正式推荐。

适合展示的流程图：

```text
自然语言/结构化输入
      -> alias linking + rule parsing
      -> normalized node scores
      -> GraphLoader 编译 core/aux 通道
      -> InferenceEngine DAG 传播
      -> formal / near miss / bridge
      -> path explanation / gap / what-if simulation
```
