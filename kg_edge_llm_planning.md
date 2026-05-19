# KG 扩展边规划问题记录

## 当前问题

`sx` 分支的 `37bf755` commit 已经把实体扩展到 `398` 个节点：

- 原 KG 节点：`365`
- 新增候选节点：`33`
- 节点层级仍沿用五层：`evidence`、`ability`、`composite`、`direction`、`role`

但该 commit 同时生成了 `79,003` 条两两边，相当于对 `398` 个节点做全连接：

```text
398 * 397 / 2 = 79,003
```

其中只有 `937` 条来自原 `data/seeds/edges.json`，其余 `78,066` 条是启发式补全。这个规模和生成方式不适合直接引入 KG，否则会稀释图谱语义，也可能破坏现有推理逻辑。

## 目标

保留实体扩展成果，但重新设计扩边流程：

1. 不把 `79,003` 条全连接边全部引入 KG。
2. 只为合理的 `节点 X 节点` 组合生成候选边。
3. 使用 LLM，例如 DeepSeek，对候选边进行关系规划，并尽量组织成稳定 prompt 以利用 DeepSeek 的缓存能力。
4. 关系类型只允许：
   - `support`
   - `requires`
   - `prefers`
   - `inhibits`
   - `none`
5. 不再使用 `evidences`，因为它已经合并进 `support`。

## 设计思路

先用规则生成较小的候选对，再让 LLM 判断关系，而不是让 LLM 或规则处理完整全连接图。

候选对来源可以包括：

- 原 KG 已存在边，两端节点保留为高优先级候选。
- 新增 33 个节点与语义相近的旧节点。
- 同一类别或相邻层级之间的 top-k 候选。
- 有共享 alias、关键词、source record、外部引用的节点对。
- 明确不合理的组合直接跳过，例如两个无关 evidence 节点之间默认不建边。

LLM 对每个候选对输出结构化结果：

```json
{
  "source": "node_a",
  "target": "node_b",
  "relation": "support | requires | prefers | inhibits | none",
  "confidence": 0.0,
  "reason": "简短依据",
  "needs_review": true
}
```

当 `relation = none` 时，不进入正式 KG 边，只保留在审计或负样本文件中。

## 给 DeepSeek 的语义说明

为了让 DeepSeek 更稳定地理解任务，需要在稳定 prompt 前缀中明确节点层级和边类型。

### 五类节点

| 节点层级 | 含义 | 例子 |
| --- | --- | --- |
| `evidence` | 用户输入或简历/JD 中能直接观察到的原子证据，包括技能、工具、知识点、项目经历、兴趣偏好、约束短板等。它通常是图谱最底层的事实信号。 | Python、Docker、RAG、数据清洗、不擅长 C++ |
| `ability` | 由多个 evidence 支撑出来的基础能力单元，表示用户具备某类可迁移能力。 | 后端技术栈、数据工具链、沟通能力 |
| `composite` | 多个 ability 组合形成的复合能力或岗位能力画像，比单一能力更接近职业方向。 | 数据工程能力、Web 开发能力、机器学习应用能力 |
| `direction` | 职业/岗位方向，表示用户可能适配的一类发展方向。它通常由 composite、ability、interest、constraint 共同影响。 | 后端方向、数据方向、算法方向 |
| `role` | 具体岗位或职业角色，是推荐/规划时更接近最终输出的节点。 | 后端工程师、数据工程师、算法工程师 |

### 四种边

| 关系 | 含义 | 方向判断 |
| --- | --- | --- |
| `support` | A 正向支撑 B。A 的存在会提高 B 的成立、匹配或推荐强度。`evidences` 已合并到这里，不再单独输出。 | 通常从更底层、更具体的节点指向更高层、更抽象的节点，例如 `Python -> 后端技术栈`。 |
| `requires` | B 需要 A 作为关键前置或必要基础。没有 A 时，B 的成立会明显变弱。 | 从前置条件指向被依赖对象，例如 `数据结构 -> 算法能力`。 |
| `prefers` | A 是偏好、兴趣或倾向，会提高 B 的适配度，但不是能力上的必要条件。 | 通常从 interest 类 evidence 指向 direction/role，例如 `偏好数据 -> 数据方向`。 |
| `inhibits` | A 是约束、短板或反偏好，会抑制 B 的适配度。 | 通常从 constraint 类 evidence 指向被抑制的 direction/role/ability，例如 `不喜欢值班 -> 运维方向`。 |

如果两个节点之间没有清晰的语义关系，必须输出 `none`，不要为了连边而强行选择 `support`。

## DeepSeek 缓存使用方式

这里的数据规模不大，不需要设计复杂的本地缓存系统。更重要的是让请求形态稳定，充分利用 DeepSeek 服务侧的缓存能力。

建议：

- 固定 system prompt，不在每个请求里动态改写规则。
- 固定关系定义、五层节点定义和输出 JSON schema，并放在 prompt 前部。
- 固定候选边判定模板，只替换批次中的节点对数据。
- 按节点类型或候选生成规则分批，例如 evidence→ability、evidence→composite、interest→direction、constraint→role。
- 每批尽量使用相同的说明前缀，让 DeepSeek 的前缀缓存更容易命中。
- 每个 batch 输出多个候选边判断，减少请求次数。

可以把稳定前缀设计成：

```text
你是职业知识图谱关系审核器。
节点只有五层：evidence、ability、composite、direction、role。
evidence 是可观察的原子证据；ability 是基础能力；composite 是复合能力；direction 是职业方向；role 是具体岗位。
允许的关系只有 support、requires、prefers、inhibits、none。
support 表示正向支撑；requires 表示关键前置；prefers 表示偏好加成；inhibits 表示约束抑制；none 表示无明确关系。
evidences 已合并为 support，不要输出 evidences。
如果没有清晰关系，请输出 none，不要强行连边。
请只输出 JSONL，每行对应一个候选节点对。
```

动态部分只放候选对：

```json
{
  "source": {"id": "node_a", "name": "...", "layer": "evidence", "category": "tool"},
  "target": {"id": "node_b", "name": "...", "layer": "ability", "category": "ability"},
  "candidate_rule": "shared_keyword"
}
```

本地只需要保留最简单的断点续跑记录即可，例如已经完成的 batch id 和输出文件；不需要为当前数据规模单独设计 SQLite/KV 缓存。

## 输出建议

不要直接生成可替换 `seeds/edges.json` 的全量边文件。先输出候选文件：

```text
data/entity_expansion/llm_edge_candidates.jsonl
data/entity_expansion/llm_edge_candidates.summary.json
data/entity_expansion/llm_edge_batches.json
```

候选边按状态区分：

- `accepted_auto`：高置信，可考虑入库
- `review_required`：需要人工确认
- `rejected_none`：LLM 判定无关系，作为审计/负样本保留

最终只有 `accepted_auto` 和人工确认后的 `review_required` 才能进入正式 KG。

## 当前判断

`37bf755` 的 398 节点扩展产物可以作为实体扩容基础；但 `79,003` 条 pairwise edges 只能作为问题样例或候选生成参考，不能整包进入 KG。
