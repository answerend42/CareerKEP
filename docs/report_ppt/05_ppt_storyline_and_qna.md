# PPT 讲法与可能追问

## 推荐 PPT 主线

建议按知识工程生命周期讲，而不是按 Git 分支讲。这样更容易和老师课件对齐。

### Slide 1：项目目标

标题建议：

```text
CareerKEP：基于知识图谱的计算机职业推荐系统
```

要讲清楚：

- 输入：用户的技能、项目、兴趣、约束。
- 中间：职业知识图谱。
- 输出：正式推荐、near miss、bridge、差距分析、行动建议。

对应课件：课程概述、第 1 章“从数据到知识”。

### Slide 2：整体知识工程流程

图示：

```text
数据获取 -> 清洗 -> 实体识别 -> 实体消歧/链接
       -> Schema -> 关系抽取 -> 图谱构建
       -> 图谱推理 -> 推荐解释
```

对应分工：

- ztt & qyw：数据获取、清洗、实体仓库。
- lsy & ljc：seed 图谱扩容。
- sx & wxs：关系设计和 DeepSeek 边规划。
- jrh & syg：输入处理和后端推理。

### Slide 3：知识体系设计

展示五层节点：

```text
evidence -> ability -> composite -> direction -> role
```

展示四类边：

```text
supports / requires / prefers / inhibits
```

要强调：

- 这是项目自己的 Knowledge Schema。
- 节点和关系不是随便加的，必须符合 schema。
- `evidences` 已经并入 `supports`，保证前端、后端、报告术语一致。

对应课件：第 3 章 Knowledge Schema、本体、关系。

### Slide 4：entityRepo 数据获取和实体仓库

讲法：

```text
这一部分从 JD、简历、SkillSpan、ESCO、O*NET 中获取实体和别名。
它不直接改线上图谱，而是生成可审阅的实体仓库和实体链接材料。
```

可展示数字：

- 1,288 份 staged 文档。
- 173 个 entityRepo 实体。
- 14 个 extracted 新实体。
- 490 个唯一别名。
- 59 个外部标准引用。
- 1,241 条消歧 review 行。

对应课件：第 4 章实体识别、第 5 章实体消歧。

### Slide 5：data_engine seed 扩容

讲法：

```text
这一部分从已有 seed 图谱出发，抓 GitHub、roadmap、Wikipedia、O*NET 语料，
再生成节点、别名和关系候选，最后通过 review/apply/rollback 安全入图。
```

可展示数字：

- 34 -> 54 节点，新增 20 个 evidence 节点。
- V5 扩展到 151 节点。
- alias entries 170 -> 361。
- mentions 91 -> 126,907。

对应课件：第 4 章实体扩展、第 6 章关系候选、第 8 章图谱数据管理。

### Slide 6：关系设计与 DeepSeek 关系抽取

讲法：

```text
398 个节点如果全连接会有 79,003 条边，不能直接入图。
所以我们改成候选边 + DeepSeek 限定域关系分类 + 置信度过滤。
```

可展示数字：

- 12,573 个候选行。
- 10,211 个被判为 `none`。
- 2,362 个非 `none` 关系。
- 20 个 very-low 被排除。
- 最终保留 398 节点、3,395 边。

对应课件：第 6 章关系抽取、三元组、有序关系。

### Slide 7：最终 KG 状态

展示：

| 指标 | 数量 |
| --- | ---: |
| 原始节点 | 365 |
| 扩展后节点 | 398 |
| 新增节点 | 33 |
| 原始 seed 边 | 1,053 |
| 清洗后全量边 | 3,395 |

要讲清楚：

- 原始 seed 边全部保留。
- LLM very-low 边被排除。
- 这张图是 review graph，不等于所有边都直接进入正式推荐评分。

### Slide 8：后端推理为什么要拆 core/aux

讲法：

```text
扩展图谱能带来更多候选，但也会带来弱边噪声。
所以后端把边分成 core 和 aux：
core 负责正式判断，aux 负责发现可能性。
```

可展示：

```text
core_score  -> formal recommendation gate
aux_score   -> near miss / bridge / gap suggestion
score       -> 展示排序辅助
```

对应课件：第 9 章知识推理。

### Slide 9：演示案例

建议三个案例：

1. `我会 Python Java Spring Boot MySQL 喜欢后端`
   - 正式推荐后端/Java 后端。
   - Rust 只 near miss，因为没有 Rust 锚点。
2. `我会 Rust Linux 做过低延迟服务项目 喜欢后端`
   - Rust 服务工程师进入正式推荐。
3. 结构化输入 `LLM=0.9`
   - LLM 激活大模型/NLP方向。
   - 不直接 formal 推荐岗位，除非有足够 core 证据。

### Slide 10：总结与不足

总结：

- 我们完成了从数据到知识、从知识到推理的完整链路。
- 图谱从 365 节点扩展到 398 节点。
- 关系从 seed 边扩展到 3,395 条清洗审阅边。
- 推理端用 core/aux 机制避免 LLM 边直接污染正式推荐。

不足：

- entityRepo 的部分聚类仍需人工复核。
- LLM 关系边目前是未审阅或半审阅状态，后续应引入 promoted/reviewed 标记。
- 专项岗位锚点规则目前是启发式，后续可配置化。
- 还可以补充更多 benchmark 和人工评估。

## 老师可能追问

### Q1：你们的知识图谱 schema 是什么？

答：

我们用了五层 schema：

```text
evidence -> ability -> composite -> direction -> role
```

其中 evidence 是用户可直接输入的原子证据，role 是最终推荐岗位。边只有四类：`supports`、`requires`、`prefers`、`inhibits`。这相当于项目里的领域本体/Knowledge Schema。

### Q2：数据获取和实体扩展有什么区别？

答：

entityRepo 是从外部 JD、简历、SkillSpan、ESCO/O*NET 中抽实体，重点是实体仓库、别名、消歧和链接材料。data_engine 是从已有 seed 节点出发抓公开语料，重点是围绕原图谱做可控扩容。一个偏“外部数据到实体仓库”，一个偏“seed 图谱向外扩展”。

### Q3：为什么不用 79,003 条全连接边？

答：

全连接只是数学上可能的节点对，不代表知识图谱中的真实关系。直接加入会让图谱过密、语义变弱、推理失控，也无法人工审核。所以我们只保留候选边，并让 DeepSeek 在限定关系集合里判断，最后过滤掉 `none` 和 very-low。

### Q4：DeepSeek 做的是什么任务？

答：

它做的是限定域关系抽取/关系分类。输入是候选节点对，输出只能是 `support/requires/prefers/inhibits/none` 和置信度。不是让模型自由编造知识，而是在固定 schema 下做关系判断。

### Q5：LLM 生成的边会不会影响推荐可靠性？

答：

会有这个风险，所以后端没有让 LLM 边直接进入正式推荐门槛。系统把边分成 core 和 aux：core 主要是 seed/curated 边，负责 formal recommendation；LLM 边默认是 aux，只帮助 near miss、bridge、候选发现和补齐建议。

### Q6：为什么分数要拆成 core_score 和 aux_score？

答：

因为“图谱关系”和“正式评分策略”不是同一件事。LLM 边可能语义上相关，但不一定足以证明用户达到岗位要求。`core_score` 表示正式证据，`aux_score` 表示辅助发现信号。正式推荐要求 `core_score` 达到门槛。

### Q7：专项岗位锚点是什么？

答：

专项岗位如 Rust、React、NLP、LLM、MLOps 不能只靠通用后端或通用编程能力推荐。系统会检查用户输入或 core evidence 中是否有对应技术锚点，例如 Rust 岗位需要 Rust 相关证据。没有锚点时可以 near miss，但不能 formal。

### Q8：这和普通推荐系统有什么不同？

答：

普通推荐系统可能直接用特征向量或模型排序。我们的系统显式维护了知识图谱，推荐结果可以回溯到路径：哪些 evidence 支撑了哪些 ability，进而支撑哪个 role。它更强调可解释性、可审阅性和知识推理过程。

## 最简单的人话版总结

可以在口头汇报中这样说：

> 我们先定义了职业知识图谱的结构：五类节点和四类边。然后一部分同学负责从简历、岗位和公开数据里抽实体，一部分同学负责从已有 seed 图谱出发自动扩容，一部分同学负责用 DeepSeek 判断候选节点之间的关系，最后后端把图谱用于推荐推理。为了避免 LLM 边让推荐变得太宽，我们把图谱边分成 core 和 aux：core 决定正式推荐，aux 帮助发现候选和补齐路径。
