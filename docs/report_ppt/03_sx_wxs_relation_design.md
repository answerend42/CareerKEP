# sx & wxs：关系设计与 DeepSeek 扩展边规划

对应分支：`sx`
关键 commits：

- `37bf755`：加入 398 节点扩展思路和 pairwise edges。
- `27867a8`：加入 LLM 关系规划流水线和输出。

## 一句话定位

这个部分负责把“新增实体”变成“可用知识图谱”。重点不是简单增加节点，而是设计哪些节点之间应该连边、连什么关系、哪些边应该进入正式图谱。

用课程术语说，它对应：

```text
知识体系构建 -> 关系抽取 -> 三元组构建 -> 质量控制
```

## 与课件知识点的对应

| 课件知识点 | 分支里的实现 |
| --- | --- |
| 第 3 章：知识体系 | 明确五层节点、四类关系，约束边的合法语义 |
| 第 6 章：关系抽取 | 对节点对判断 `support/requires/prefers/inhibits/none` |
| 第 6 章：有序关系 | 关系有方向，例如 `Python -> 后端技术栈` |
| 第 8 章：三元组表示 | 每条边都可以看作 `<source, relation, target>` |
| 第 9 章：推理前提 | 关系边会影响后端传播，因此必须控制质量 |

## 为什么不能直接全连接

`37bf755` 曾经把节点扩到 398 个：

```text
365 个原始节点 + 33 个新增候选节点 = 398 个节点
```

如果对 398 个节点做无向两两配对，会得到：

```text
398 * 397 / 2 = 79,003 条候选边
```

这不能直接引入 KG，原因有三个：

1. 图谱语义会被稀释：太多边会让“真实关系”和“弱相关”混在一起。
2. 推理会失控：职业推荐会被大量弱边拉高。
3. 人工审核不可行：79,003 条边无法逐条检查。

所以 SX 的第二次改进不是“保留全连接”，而是转向“候选边 + LLM 判断 + 置信度过滤”。

## 统一后的关系体系

最终只允许四种关系，`evidences` 已合并到 `support/supports`。

| 关系 | 含义 | 方向 |
| --- | --- | --- |
| `support` / runtime `supports` | A 正向支撑 B，会提高 B 的成立或匹配程度 | 通常从更具体、更底层指向更抽象、更高层 |
| `requires` | B 需要 A 作为关键前置条件 | 从前置条件指向被依赖对象 |
| `prefers` | A 是偏好或倾向，会温和提高 B 的适配度 | 多见于 interest -> direction/role |
| `inhibits` | A 是约束或短板，会降低 B 的适配度 | 多见于 constraint -> direction/role |

如果两个节点之间没有清晰关系，则输出 `none`，不强行连边。

## DeepSeek 关系规划

SX 的设计是让 DeepSeek 做限定域关系分类，而不是开放式自由生成。

输入给模型的是候选节点对：

```json
{
  "source": {"id": "skill_python", "name": "Python", "layer": "evidence"},
  "target": {"id": "cap_backend_stack", "name": "后端技术栈", "layer": "ability"},
  "candidate_rule": "layer_transition"
}
```

模型只能输出：

```json
{
  "relation": "support | requires | prefers | inhibits | none",
  "confidence": 0.0,
  "reason": "简短依据",
  "needs_review": true
}
```

这对应课件第 6 章的“限定域关系抽取”：关系类别是预先定义好的，模型任务是在候选实体对之间选择关系。

## DeepSeek 缓存使用

这里的数据量不大，不需要复杂的本地缓存系统。真正重要的是使用 DeepSeek 服务侧的前缀缓存：

- 固定 system prompt。
- 固定五层节点定义。
- 固定四类关系定义。
- 固定 JSON 输出 schema。
- 动态部分只替换候选节点对。
- 按候选类型分批，例如 evidence -> ability、ability -> composite、interest -> direction。

这样相同的长 prompt 前缀更容易命中 DeepSeek 的缓存，减少成本和延迟。

## 置信度筛选

`27867a8` 输出了 DeepSeek 判断结果。当前 main 中保留的是非 `none` 且非 very-low 的关系边。

DeepSeek 关系判断统计：

| 类别 | 数量 |
| --- | ---: |
| 输入候选行 | 12,573 |
| accepted relation rows | 2,362 |
| rejected none rows | 10,211 |
| high confidence (`>= 0.86`) | 828 |
| medium confidence (`0.70 - 0.86`) | 1,206 |
| low confidence (`0.50 - 0.70`) | 308 |
| very low confidence (`< 0.50`) | 20 |

按关系类型统计：

| 关系 | 数量 |
| --- | ---: |
| support | 1,893 |
| requires | 185 |
| prefers | 183 |
| inhibits | 101 |

当前清洗策略：

```text
保留 confidence >= 0.5 的 LLM 边
排除 confidence < 0.5 的 very-low 边
原始 seed 边全部保留
```

## 最终扩展图谱

当前 main 的清洗扩展图谱：

| 指标 | 数量 |
| --- | ---: |
| 节点 | 398 |
| 原始 seed 节点 | 365 |
| 新增节点 | 33 |
| 总边数 | 3,395 |
| 保留 seed 边 | 1,053 |
| 保留 LLM 边 | 2,342 |
| 排除 very-low LLM 边 | 20 |

关键文件：

| 文件 | 用途 |
| --- | --- |
| `data/entity_expansion/entity_expansion_nodes.json` | 398 节点实体列表 |
| `data/entity_expansion/entity_expansion_nodes.summary.json` | 节点数量、层级、类型统计 |
| `data/entity_expansion/llm_edge_judgments.accepted.json` | DeepSeek 非 `none` 判断结果 |
| `data/entity_expansion/llm_expanded_graph.clean.json` | 最终清洗扩展图谱 |
| `data/entity_expansion/edge_confidence_review/` | 按置信度分桶的人工查看材料 |
| `frontend/public/kg-expanded-clean-overview.html` | 扩展图谱总览 |

重建脚本：

```bash
python3 data/scripts/build_entity_expansion_nodes.py
python3 data/scripts/build_llm_edge_candidates.py
python3 data/scripts/run_deepseek_edge_judgments.py
python3 data/scripts/compact_llm_edge_judgments.py
python3 data/scripts/build_llm_expansion_graph.py
```

## 对最终系统的贡献

SX & WXS 的贡献可以分成三层：

1. 结构贡献：把图谱扩到 398 节点，保留五层 schema。
2. 关系贡献：用 DeepSeek 对候选节点对做限定域关系判断。
3. 质量贡献：排除 `none` 和 very-low，避免把全连接边直接引入 KG。

最重要的是第三点。它让扩展图谱可用于后端推理，而不是变成一张过密、不可解释的图。

## PPT 可讲重点

可以用下面的话概括：

> sx & wxs 做的是关系设计和关系抽取。第一次尝试发现 398 个节点全连接会产生 79,003 条边，不能直接进 KG；后来改成候选边加 DeepSeek 限定域关系判断，只保留 support、requires、prefers、inhibits 四类非 none 关系，并按置信度筛掉 very-low 边。最终形成 398 节点、3,395 边的清洗扩展图谱。

适合展示的流程：

```text
398 nodes
   -> candidate node pairs
   -> DeepSeek relation classification
   -> confidence buckets
   -> remove none and very-low
   -> clean expanded KG
```
