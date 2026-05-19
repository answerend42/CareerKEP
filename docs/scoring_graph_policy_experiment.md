# Scoring Graph Policy Experiment

本分支用于验证扩展图谱进入推荐系统后的最小安全改造。目标不是把某几条 LLM 边权重调低，而是把“知识图谱关系”和“正式推荐评分策略”拆开。

## 图谱分层

当前实现没有新增独立存储文件，而是在 `GraphLoader` 编译运行时图谱时拆出三类用途：

| 名称 | 实现位置 | 用途 |
| --- | --- | --- |
| ReviewGraph | `graph.all_edges` | 全量审阅图，保留 seed 边、LLM 边、same-layer 边、解释边 |
| ScoringGraph | `graph.edges` 中 `channel == "core"` | 正式推荐骨架，只由 seed / curated 边打开正式岗位门槛 |
| AuxGraph | `graph.edges` 中 `channel == "aux"` 与 `graph.aux_edges` | LLM 辅助语义，供 near miss、bridge、候选扩展、解释审阅使用 |

扩展图通过环境变量加载：

```bash
CAREER_KEP_GRAPH_BUNDLE=data/entity_expansion/llm_expanded_graph.clean.json
```

## 边策略

边的 `relation` 仍表示知识语义：

- `supports`：正向支持。
- `requires`：前置要求。
- `prefers`：偏好加成。
- `inhibits`：抑制项。

运行时新增评分策略字段：

- `channel`: `core` / `aux` / `similarity` / `explain`
- `scoring_policy`: `positive_support` / `hard_requirement` / `soft_requirement` / `soft_support` / `aux_preference` / `negative_penalty` / `similarity_only` / `explain_only`
- `provenance`: `curated` / `llm_unreviewed`
- `trust`
- `eligible_for_gate`
- `eligible_for_formal_score`

默认策略：

| 来源 | 默认 channel | 是否能开正式 hard gate |
| --- | --- | --- |
| seed / preserved_seed | `core` | 只有 curated `requires` 可以 |
| LLM forward supports/requires/prefers | `aux` | 否 |
| LLM same-layer | `similarity` | 否 |
| LLM backward requires | 反转成 layer-order 的 `aux soft_requirement` | 否 |
| LLM inhibits | `explain` | 否 |

## 推理变化

`InferenceEngine` 现在输出双通道状态：

- `core_score`: 只来自 core 图，用于正式推荐门槛。
- `aux_score`: 来自 LLM 辅助边，有严格 cap。
- `score`: `core_score + aux_score` 的展示/排序信号。
- `formal_eligible`: role 必须有足够 `core_score` 才能进入正式推荐。

核心思想：

```text
final_score = core_score + capped_aux_score
formal recommendation requires core_score >= FORMAL_CORE_THRESHOLD
```

`requires` 不再以 1.0 完整加入正向分。当前实验参数：

```text
curated requires positive factor = 0.65
aux requires positive factor     = 0.55
aux role cap                     = 0.08
aux non-role cap                 = 0.12
```

聚合时使用 noisy-or 处理根证据，减少多路径重复堆分。

## 专项岗位锚点

专项岗位不能只靠通用后端、Web 基础、单一通用技能进入正式推荐。当前实现对以下岗位要求专项锚点：

- `metadata.role_kind == "specialization"` 的 role。
- role id 中带有 `python`、`java`、`rust`、`react`、`vue`、`nlp`、`llm`、`mlops` 等技术专项 token 的 role。

专项锚点来自用户直接输入或 core evidence 中命中的专项根证据。例如：

- `Rust` 可以打开 `role_rust_backend_engineer`。
- 只有 Python / Java / Spring Boot / MySQL / 后端偏好时，`role_rust_backend_engineer` 只能进入 near miss，不进入正式推荐。

## 已覆盖回归

新增扩展图回归：

- Python only：不产生正式 role recommendation，只产生 near miss / bridge。
- HTML only：不正式推荐安全、DevOps、QA 等大片岗位。
- LLM only：大模型相关岗位只进 near miss / bridge，不直接 formal。
- Backend bundle without Rust：Java / 通用后端可以 formal，Rust 保持 near miss。
- Rust anchor：输入 Rust + Linux + 低延迟服务项目后，Rust 服务工程师可以 formal。

验证命令：

```bash
PYTHONPATH=. pytest tests -q
```
