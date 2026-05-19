# 扩展知识图谱后的推理策略说明与演示案例

这份文档用于给老师解释：为什么扩展 KG 后不能把所有 LLM 生成的边直接放进正式推荐评分，以及当前实验分支如何做到“能扩展候选，又不乱给正式岗位结论”。

## 一句话结论

当前实验分支把扩展知识图谱分成两种用途：

- **发现可能性**：LLM 扩展边可以帮助系统发现新方向、新岗位、新缺口。
- **正式下结论**：正式岗位推荐必须主要由原始 seed / curated 图谱的 core 证据支撑。

也就是说：

```text
LLM 边可以让岗位进入 near miss / bridge
但默认不能让岗位直接进入 formal recommendation
```

这能解决扩展图谱后的核心风险：图谱变大以后，如果所有边都进入同一个传播器，单个通用技能可能会把太多岗位推成正式推荐。

## 背景：为什么要改

main 分支使用的是较小的 seed 图谱：

```text
365 个节点
1053 条边
```

当前实验分支加载扩展图谱后是：

```text
398 个节点
3395 条全量审阅边
其中 2521 条进入运行时传播
874 条保留为 aux / similarity / explain
```

扩展图谱带来了更多实体，例如 LLM、大模型、RAG、LangChain、更多专项岗位相关节点。但问题也随之出现：如果把 LLM 生成的边全部当作正式评分事实，推荐会变宽，解释会变弱。

例如：

```text
用户只输入 “LLM”
```

系统可以判断这和“大模型应用工程师”“NLP 工程师”“AI 应用方向”有关，但不应该直接正式推荐“大模型应用工程师”。因为这只是一个方向信号，不足以证明用户已经具备岗位要求。

## main 的旧逻辑

main 的推理方式可以概括为：

```text
一个 runtime graph
一个 score
所有 relation 直接参与传播
role 节点按 score 排序
```

旧逻辑中，边主要只有知识语义：

```text
supports / requires / prefers / inhibits
```

问题是：`requires` 同时承担两个职责：

1. 表示知识上“这个岗位需要这个能力”。
2. 在评分里既参与门槛，又贡献正向分。

在 seed 图谱规模较小时，这个设计可控。但扩展图谱里 LLM 边很多，如果 LLM 生成的 `requires` 也进入正式传播，就容易把“可能相关”变成“正式达标”。

## 当前实验分支的新逻辑

当前分支做了一个最小重构：关系语义不变，但新增评分策略。

一条边现在不仅有：

```text
relation = supports / requires / prefers / inhibits
```

还会有：

```text
channel = core / aux / similarity / explain
scoring_policy = positive_support / hard_requirement / soft_requirement / ...
provenance = curated / llm_unreviewed
eligible_for_gate = true / false
trust = 可信度折扣
```

### 三种图的用途

| 图 | 实现 | 用途 |
| --- | --- | --- |
| ReviewGraph | `graph.all_edges` | 全量审阅图，保留 seed 边、LLM 边、同层边、解释边 |
| ScoringGraph | `channel == core` | 正式评分骨架，只由 curated seed 边打开岗位门槛 |
| AuxGraph | `channel == aux/similarity/explain` | 辅助发现候选、near miss、bridge、gap suggestion |

### 边的默认处理

| 边来源 | 默认处理 | 是否能打开正式岗位门槛 |
| --- | --- | --- |
| seed / preserved_seed | `core` | curated `requires` 可以 |
| LLM forward supports/requires/prefers | `aux` | 不可以 |
| LLM same-layer | `similarity` | 不可以 |
| LLM backward requires | 反转成 `aux soft_requirement` | 不可以 |
| LLM inhibits | `explain` | 不可以 |

## 当前分数计算

每个节点现在有三个重要分数：

```text
core_score  正式评分骨架分
aux_score   LLM 辅助信号分
score       core_score + aux_score
```

正式推荐不是只看 `score`，而是要求：

```text
role.formal_eligible = core_score >= 0.05
```

因此：

```text
LLM 可以提高 aux_score
但 aux_score 不能打开 formal recommendation
```

### 传播公式

每条边先计算父节点贡献：

```text
contribution =
  parent_score
  * edge_weight
  * relation_factor
  * edge_trust
```

其中：

- core 边使用父节点的 `core_score`。
- aux 边使用父节点的最终 `score`。
- `prefers` 的 relation factor 是 `0.75`。
- 未审阅 LLM 边的 trust 是 `0.15`。

### 根证据聚合

同一个用户输入可能通过多条路径到达同一个节点。为了避免重复堆分，当前实现用 noisy-or 聚合：

```text
noisy_or(xs) = 1 - Π(1 - x_i)
```

这意味着多条弱路径可以共同增强，但不会无限相加。

### core 分

core 正向分：

```text
core_base_positive =
  supports
  + requires * 0.65
  + prefers
  + direct_input
```

这里刻意让 `requires` 低于普通正向支持。原因是：`requires` 主要应该决定门槛，而不是强行加分。

再经过聚合器：

| 聚合器 | 作用 |
| --- | --- |
| `soft_and` | 要求多个父节点共同支撑，覆盖不足会降分 |
| `max_pool` | 取最强父节点 |
| `penalty_gate` | 要求不足时按比例降分 |
| `hard_gate` | role 的关键要求不足时归零 |

最后扣除抑制项：

```text
core_score = max(0, core_base_score - inhibit_total * 0.82)
```

### aux 分

aux 分只作为辅助：

```text
aux_score =
  min(aux_cap, aux_support + aux_require * 0.55 + aux_prefer * 0.45)
```

上限：

```text
role 节点 aux cap = 0.08
非 role 节点 aux cap = 0.12
```

这保证 LLM 边能影响 near miss / bridge，但不会把岗位直接推成 formal。

## 专项岗位锚点

有些岗位是专项岗位，例如：

```text
Rust 服务工程师
React 前端工程师
NLP 工程师
大模型应用工程师
MLOps 工程师
```

这些岗位不能只靠“后端”“Web”“编程基础”进入正式推荐。当前实验分支要求它们有专项锚点。

例如：

```text
Python + Java + Spring Boot + MySQL + 后端偏好
```

这说明用户是后端方向，但不能证明用户适合 Rust 服务工程师。

所以当前结果是：

```text
Rust 服务工程师进入 near miss
但不进入 formal recommendation
```

而：

```text
Rust + Linux + 低延迟服务项目 + 后端偏好
```

有 Rust 专项锚点，因此 Rust 服务工程师可以进入正式推荐。

## 演示案例

### 案例 1：扩展候选但不乱推 Rust

前端可直接输入：

```text
我会 Python Java Spring Boot MySQL 喜欢后端
```

main 结果：

| 类型 | 结果 |
| --- | --- |
| formal | `role_java_backend_engineer` |
| near miss | `role_api_platform_engineer`, `role_microservice_engineer`, `role_backend_engineer`, `role_rust_backend_engineer` |

当前实验分支结果：

| 类型 | 结果 |
| --- | --- |
| formal | `role_java_backend_engineer`, `role_backend_engineer` |
| near miss | `role_php_backend_engineer`, `role_python_backend_engineer`, `role_rust_backend_engineer`, `role_api_platform_engineer` |

讲解重点：

- 扩展图谱让系统能发现更多后端相关候选。
- Rust 被发现了，但没有 Rust 专项锚点，所以没有进入 formal。
- 这说明扩展图谱在“拓宽候选”，但正式推荐仍保持谨慎。

### 案例 2：有 Rust 锚点时才正式推荐 Rust

前端可直接输入：

```text
我会 Rust Linux 做过低延迟服务项目 喜欢后端
```

main 结果：

| 类型 | 结果 |
| --- | --- |
| formal | `role_rust_backend_engineer`, `role_performance_test_engineer` |
| near miss | `role_api_platform_engineer`, `role_microservice_engineer`, `role_backend_engineer`, `role_python_backend_engineer` |

当前实验分支结果：

| 类型 | 结果 |
| --- | --- |
| formal | `role_rust_backend_engineer` |
| near miss | `role_api_platform_engineer`, `role_python_backend_engineer`, `role_backend_engineer`, `role_php_backend_engineer` |

讲解重点：

- 用户明确提供 Rust、Linux、低延迟服务项目，因此 Rust 服务工程师可以正式推荐。
- 当前分支没有把性能测试工程师也推成 formal，而是更集中地推荐 Rust 岗位。
- 这体现了专项锚点和 core gate 对正式推荐的约束。

### 案例 3：新实体 LLM 可以用于候选发现，但不直接下岗位结论

这个案例建议用 API 演示，因为当前自然语言 parser 还没有把 `LLM/大模型` 作为文本 alias 接进去，但结构化输入可以识别。

请求：

```bash
curl -s -X POST http://127.0.0.1:8091/api/recommend \
  -H 'Content-Type: application/json' \
  -d '{"signals":[{"entity":"LLM","score":0.9}],"top_k":5}' | python3 -m json.tool
```

main 结果：

| 类型 | 结果 |
| --- | --- |
| normalized | 空，main seed 图谱没有这个实体 |
| formal | 空 |
| near miss | 空 |
| bridge | 空 |

当前实验分支结果：

| 类型 | 结果 |
| --- | --- |
| normalized | `llm` |
| formal | 空 |
| near miss | `role_llm_application_engineer`, `role_nlp_engineer`, `role_ai_application_engineer` |
| bridge | `dir_machine_learning`, `cap_nlp_engineer`, `dir_ai_application`, `cap_llm_application_engineer` |

讲解重点：

- 扩展图谱确实提供了新实体输入。
- 系统能识别 LLM 与大模型/NLP/AI 应用方向有关。
- 但只输入 LLM 不足以正式推荐大模型岗位，所以输出 near miss / bridge。
- 这正是“LLM 边负责发现方向，不负责正式开门槛”的效果。

### 案例 4：结构化后端画像，无 Rust 时 Rust 保持 near miss

请求：

```bash
curl -s -X POST http://127.0.0.1:8091/api/recommend \
  -H 'Content-Type: application/json' \
  -d '{
    "signals": [
      {"entity":"Python","score":0.85},
      {"entity":"Java","score":0.8},
      {"entity":"Spring Boot","score":0.82},
      {"entity":"MySQL","score":0.8},
      {"entity":"偏好后端","score":0.9}
    ],
    "top_k": 8
  }' | python3 -m json.tool
```

main 结果：

| 类型 | 结果 |
| --- | --- |
| formal | `role_java_backend_engineer` |
| near miss | `role_php_backend_engineer`, `role_python_backend_engineer`, `role_api_platform_engineer`, `role_microservice_engineer` |

当前实验分支结果：

| 类型 | 结果 |
| --- | --- |
| formal | `role_java_backend_engineer`, `role_backend_engineer`, `role_fullstack_engineer` |
| near miss | `role_php_backend_engineer`, `role_python_backend_engineer`, `role_rust_backend_engineer`, `role_api_platform_engineer` |

讲解重点：

- 扩展图谱增加了候选覆盖面。
- Rust 被列为 near miss，说明图谱知道它和后端方向相关。
- 但没有 Rust 锚点，所以 Rust 不会进入 formal。

## 建议的课堂讲法

可以按下面顺序讲：

1. 原系统是 KG 职业推荐，seed 图谱比较小，所有边进一个传播器可以工作。
2. 扩展图谱后，LLM 边很多，如果全部进入正式评分，会导致推荐过宽。
3. 所以我们把“知识关系”和“评分策略”拆开。
4. LLM 边保留，不丢掉；但它默认只做候选发现、near miss、bridge。
5. 正式推荐仍由 core graph 决定。
6. 对 Rust、React、NLP、大模型等专项岗位，再加专项锚点门槛。
7. 这样既能扩图，又能保持推荐解释可信。

一句话版本：

```text
我们不是不相信 LLM 边，而是不让未审阅 LLM 边直接替用户通过岗位门槛。
```

## 当前不足

这还是实验版，后续可以继续做三件事：

1. **文本 alias 补齐**：例如自然语言里的“大模型/LLM/RAG”应该直接映射到扩展实体。
2. **专项岗位锚点显式配置**：现在是基于 role id 和节点 token 的启发式规则，后续应该在 KG 数据里显式写 `role_gate`。
3. **权重校准**：当前参数是保守初值，后续可以用 benchmark 或人工标注样例校准。

## 相关代码位置

- 图加载与边策略：`backend/app/services/graph_loader.py`
- core/aux 推理：`backend/app/services/inference_engine.py`
- 正式推荐过滤与专项锚点：`backend/app/api/recommend.py`
- 回归测试：`tests/test_inference_engine.py`
