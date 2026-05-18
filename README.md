# Career KG

基于知识图谱的计算机相关职业推荐系统，功能包括：

- 图谱数据构建：从 source 数据编译运行时节点、边和词典。
- 推荐后端：自然语言解析、输入归一、图上传播、职业排序、near miss / bridge 兜底、路径解释、目标岗位差距分析和行动模拟。
- 前端工作台：输入画像、微调画像、图谱传播、结果解释四个演示阶段。

## 核心原理

1. 用户输入自然语言或结构化信号。
2. 输入被映射成标准图谱节点和 `0..1` 分值。
3. 后端加载 `data/seeds/nodes.json` 与 `data/seeds/edges.json`，按 DAG 拓扑序传播分数。
4. 图谱边的语义决定分数如何流动：支持、要求、偏好、抑制、证据。
5. 只对 `role` 层职业节点排序，输出正式推荐、near miss 和 bridge recommendation。
6. 解释器从职业节点反向回溯高贡献路径，前端用 `propagation_snapshot` 展示传播过程。

运行时图谱固定为五层：

| 层级 | 含义 | 示例 |
| --- | --- | --- |
| `evidence` | 原子证据，来自用户输入 | Python、SQL、前端项目、偏好与人交互、不擅长 C++ |
| `ability` | 基础能力 | 编程基础、数据库实践、数学基础 |
| `composite` | 复合能力 | 后端工程能力、机器学习工程能力 |
| `direction` | 岗位方向 | Web 后端、机器学习、数据方向 |
| `role` | 具体职业 | 后端开发工程师、机器学习工程师、数据工程师 |

边类型：

- `supports`：常规正向支持。
- `evidences`：项目、课程等实践证据，权重略低于普通支持。
- `requires`：关键前置，参与门槛判断。
- `prefers`：偏好加成，贡献较温和。
- `inhibits`：抑制项，会在最后扣分。

## 分数计算过程

实现入口在 `backend/app/services/inference_engine.py`。所有节点最终得到一个 `NodeState`：

- `score`：节点最终分数。
- `direct_input`：用户是否直接输入了这个节点。
- `evidence`：哪些根证据贡献了这个分数。
- `parent_contributions`：父节点通过边传来的贡献。
- `diagnostics`：支持、要求、偏好、抑制等诊断分量。

### 1. 输入分值归一

自然语言输入会先经过 `backend/app/services/nl_parser.py` 做轻量解析，结构化输入会经过 `backend/app/services/input_normalizer.py` 直接映射。两者最终都变成：

```text
node_id -> score
```

分数会被夹到 `[0, 1]`。如果输入命中的是 `evidence` 节点，该节点直接使用输入分值：

```text
evidence.score = direct_input
```

并把自己记录为根证据：

```text
evidence = { node_id: direct_input }
```

### 2. 父边贡献

非 evidence 节点会读取所有入边。每条边先计算父节点对当前节点的直接贡献：

```text
contribution = parent_score * edge_weight * relation_factor
```

当前 relation factor 为：

| 关系 | factor |
| --- | ---: |
| `supports` | `1.00` |
| `evidences` | `0.92` |
| `requires` | `1.00` |
| `prefers` | `0.75` |
| `inhibits` | `1.00` |

这些贡献会进入 `parent_contributions`，用于解释路径、诊断和前端节点详情。

### 3. 根证据去重

系统不会简单把所有路径相加。每个父节点都会携带“根证据贡献表”，传播到子节点时按根证据记录贡献：

```text
root_contribution = root_value * edge_weight * relation_factor
```

如果同一个根证据通过多条路径到达同一个节点，当前实现只保留最大的一条：

```text
relation_root_maps[relation][root_id] = max(existing, root_contribution)
```

这样可以减少重复计分。例如同一个 Python 证据同时支持“编程基础”和“后端基础”，再汇入同一职业时，不会因为路径多就被无限叠加。

### 4. 四类诊断分量

节点聚合前会先得到四个主要分量：

```text
support_total = sum(support roots) + 0.92 * sum(evidence roots)
require_total = sum(require roots)
prefer_total  = sum(prefer roots * 0.75)
inhibit_total = sum(inhibit roots)
```

说明：

- `evidences` 在边传播阶段已经乘过 `0.92`，汇总到 `support_total` 时仍按证据关系再降权，体现实践证据“强但不无限放大”的策略。
- `prefers` 在边传播阶段按 `0.75` 降权，进入偏好汇总时再次按 `0.75` 温和处理，因此偏好不会压过能力和要求。
- `inhibits` 不参与正向 base score，而是在最终阶段扣分。

基础正向分：

```text
base_positive = min(cap, support_total + require_total + prefer_total + direct_input)
```

`cap` 来自节点参数，默认是 `1.0`。

### 5. 覆盖率

部分节点要求多个父节点共同支撑。系统会统计有效父节点数量：

```text
support_parent_count = count(parent relation in supports/evidences/requires and contribution >= 0.05)
coverage = min(1.0, support_parent_count / min_support_count)
```

`coverage` 主要用于 `soft_and` 聚合器，避免单个强证据把复合能力或方向节点抬得过高。

### 6. 聚合器

每个节点在 source 数据中配置一个聚合器。当前主要聚合器如下。

#### `source`

用于 evidence 节点：

```text
score = direct_input
```

#### `weighted_sum_capped`

这是默认思路：把支持、要求、偏好和直接输入相加，再受 `cap` 限制：

```text
base_score = min(cap, support_total + require_total + prefer_total + direct_input)
```

#### `max_pool`

适合“一个强证据就足以显著激活”的节点：

```text
best_parent = max(parent contributions from supports/evidences/requires, direct_input)
base_score = min(cap, best_parent + prefer_total * 0.45)
```

#### `soft_and`

适合复合能力节点。没有有效父节点时为 `0`；有父节点时用覆盖率调节：

```text
base_score = min(cap, base_positive * (0.45 + 0.55 * coverage))
```

当覆盖率不足时，节点仍可被激活，但分数会被压低。

#### `penalty_gate`

适合方向节点。关键要求不足时不归零，而是按比例折减：

```text
ratio = require_total / required_threshold
gate_multiplier = 1.0 if ratio >= 1 else max(penalty_floor, ratio)
base_score = base_score * gate_multiplier
```

#### `hard_gate`

适合职业节点。关键要求存在且未达到阈值时直接关闭：

```text
if require_total < required_threshold:
    base_score = 0
```

这保证具体职业不会只靠兴趣或单个弱证据被正式推荐。

#### 普通 required gate

不属于 `penalty_gate` / `hard_gate` 的节点，如果配置了要求阈值，也会按要求完成度折减：

```text
ratio = require_total / required_threshold
gate_multiplier = 1.0 if ratio >= 1 else max(required_floor, ratio)
base_score = base_score * gate_multiplier
```

### 7. 抑制项扣分

最后统一处理抑制项：

```text
final_score = min(cap, max(0, base_score - inhibit_total * 0.82))
```

`0.82` 是当前 `INHIBIT_FACTOR`。它让“不擅长 C++”“不喜欢频繁 on-call”等负向画像可以明显影响职业方向，但不会直接覆盖所有正向能力证据。

### 8. 证据贡献缩放

得到最终分后，系统会把正向根证据按比例缩放到最终分：

```text
scale = final_score / sum(positive_root_map.values())
evidence[root_id] = root_value * scale
```

小于 `0.01` 的根证据会被过滤。这份 evidence map 用于：

- 推荐解释里的关键路径。
- 图谱传播页的激活节点和高贡献边。
- 结果解释里的来源路径排序。

### 9. 职业排序、near miss 和 bridge

`backend/app/api/recommend.py` 会把所有 `role` 节点按最终 `score` 排序：

1. 分数达到正式推荐阈值的进入 `recommendations`。
2. 未正式推荐但有潜在信号的岗位进入 `near_miss_roles`，用于展示“差一点”的岗位和缺口。
3. 如果输入稀疏或没有足够岗位命中，会从能力、方向等中间层生成 `bridge_recommendations`，告诉用户可以往哪个方向补充信息或能力。

## 项目组织

```text
career-kg/
  backend/app/
    main.py                         # CLI 与本地 HTTP 服务入口
    api/recommend.py                # 推荐 API 编排层
    schemas.py                      # 请求/响应数据结构
    services/
      graph_loader.py               # 加载 seed 图谱、词典、模板
      nl_parser.py                  # 自然语言解析
      input_normalizer.py           # 结构化输入归一
      inference_engine.py           # 图谱分数传播
      explainer.py                  # 路径解释
      role_gap_analyzer.py          # 目标岗位差距分析
      learning_path_planner.py      # 成长路径编排
      action_simulator.py           # 行动模拟

  frontend/
    src/app/AppShell.tsx            # 四阶段演示壳
    src/app/panes/InputPane.tsx     # 输入画像
    src/app/panes/TunePane.tsx      # 微调画像
    src/app/panes/GraphPane.tsx     # 图谱传播
    src/app/panes/ResultPane.tsx    # 结果解释
    src/app/styles/                 # 全局样式与动效
    tools/export-kg-overview-data.mjs

  data/
    sources/                        # 可编辑 source 数据
    sources/raw/                    # O*NET、roadmap.sh 等原始快照
    ontology/                       # 节点/边类型本体
    seeds/                          # 编译后的运行时 nodes/edges
    dictionaries/                   # alias、短语、解析规则
    demo/                           # 示例请求与 benchmark 报告

  scripts/
    bootstrap_demo_data.py          # 生成 demo source 并编译图谱
    source_validation.py            # 校验 source schema 与引用
    build_graph.py                  # source -> seeds/dictionaries
    validate_graph.py               # 校验运行时图谱
    run_nl_benchmark.py             # 自然语言解析回归
    run_recommendation_benchmark.py # 推荐与解释回归
    run_planning_benchmark.py       # 规划与行动模拟回归
```




