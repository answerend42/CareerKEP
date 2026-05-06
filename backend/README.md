# Career KG 后端

这是 `Career KG` 的后端实现，目标是把用户画像转成知识图谱上的标准节点，然后做分数传播、职业排序、near miss 兜底、桥接推荐和目标岗位差距分析。

## 现在包含的内容

- 自然语言解析：把“会 Python、SQL、做过前端项目”这类输入映射成图谱节点。
- 结构化输入归一：把前端或脚本传来的节点分值统一到 `node_id -> score`。
- 图谱推理：按 DAG 拓扑序传播分值，支持 `supports / evidences / requires / prefers / inhibits`。
- 推荐编排：输出正式推荐、near miss、桥接建议、目标岗位分析和传播快照。
- 元信息接口：提供图谱概览，方便前端启动时读取节点层级和职业节点列表。
- 本地服务：提供 `GET /health`、`GET /api/meta` 和 `POST /api/recommend`。

## 目录

```text
backend/
  app/
    main.py
    api/recommend.py
    schemas.py
    services/
  data/
    seeds/
    dictionaries/
  pyproject.toml
```

## 图谱数据契约

后端把 `backend/data/seeds/` 和 `backend/data/dictionaries/` 视为已编译的运行时图谱边界。这里的 `nodes.json`、`edges.json` 和 `aliases.json` 不是临时演示文件；它们是推荐链路启动前必须满足的输入契约。

运行时图谱节点需要满足这些基本规则：

- `id` 必须唯一、非空，并使用小写 `snake_case`。
- `layer` 只允许 `evidence`、`ability`、`composite`、`direction`、`role`。
- `aggregator` 只允许 `source`、`weighted_sum_capped`、`max_pool`、`soft_and`、`penalty_gate`、`hard_gate`。
- 除非代码中有明确例外，`source` 聚合器只用于 `evidence` 节点。
- 节点分数字段 `cap`、`required_threshold`、`required_floor`、`penalty_floor` 必须是有限数，并位于 `0..1`。
- `min_support_count` 必须是非负整数。

运行时图谱边需要满足这些基本规则：

- `source` 和 `target` 必须指向已有节点。
- `relation` 只允许 `supports`、`evidences`、`requires`、`prefers`、`inhibits`。
- `weight` 必须是有限数，并位于 `0..1`。
- 图谱必须是 DAG，并保持从 `evidence` 到 `role` 的正向层级流动；允许跳层时必须由后端校验规则显式定义。

别名词典需要满足这些基本规则：

- `aliases.json` 的每个 key 必须指向已有节点。
- alias 在归一化后不应在无关节点之间静默冲突。
- 目标岗位解析、自然语言解析和本地图谱诊断应复用一致的 alias 归一化语义。

## 启动方式

### 1. 直接跑一次推荐

```bash
python3 -m backend.app.main recommend --text "我会 Python、SQL，做过前端项目，也比较擅长沟通" --top-k 5
```

`recommend` 子命令支持二选一的输入方式：

- `--payload-json`：直接传 JSON 字符串
- `--payload-file`：传 JSON 文件路径

两者不能同时使用。`--payload-file -` 表示从标准输入读取 JSON。参数问题返回 `2`，内部执行错误返回 `1`。如果 JSON 不是对象，也会按参数错误处理。

### 2. 启动 HTTP 服务

```bash
python3 -m backend.app.main serve --host 127.0.0.1 --port 8000
```

### 3. 运行后端自测

```bash
python3 -m unittest discover -s backend/tests
```

这套自测里包含纯函数校验、HTTP handler 校验和一次真实的本地 HTTP 往返检查，主要用来保证入口层真的能跑通。

### 4. 校验本地图谱产物

```bash
python3 -m backend.app.main validate-graph
```

这个命令会加载 `backend/data/seeds/` 和 `backend/data/dictionaries/` 下的运行时产物，输出节点数、边数、层级分布、关系分布、聚合器分布、alias 数量和校验 warning。校验通过返回 `0`，图谱契约错误返回 `2`。

接口：

- `GET /health`
- `GET /api/meta`
- `POST /api/recommend`

`GET /api/meta` 返回图谱节点数、边数、分层统计、关系统计、聚合器统计、基础校验状态、所有 `role` 节点列表，以及可直接用于前端搜索下拉的 `role_options`。

- `POST /api/recommend` 需要带 `Content-Type: application/json`，否则返回 `415`
- `POST /api/recommend` 的请求体上限是 `1 MiB`，超过后返回 `413`
- `POST /api/recommend` 会把请求体解析错误返回 `400`，服务端内部异常返回 `500`

请求体示例：

```json
{
  "text": "我会 Python、SQL，做过前端项目，也比较擅长沟通",
  "target_role": "后端开发工程师",
  "top_k": 5
}
```

`target_role` 支持 `node_id`、中文标签和词典别名，后端会自动统一解析成图谱中的岗位节点。
其中 `evidence` 支持 `node_id` / `id`、`score`、`source`、`raw_text` 这几类字段，其他附加字段会被忽略；`evidence` 也可以是单个对象或列表，列表里的无效项会被跳过，方便前端和脚本自由携带调试信息。

返回中包含：

- `input_trace`
- `recommendations`
- `near_miss_roles`
- `bridge_recommendations`
- `target_role_analysis`
- `propagation_snapshot`
- `graph_snapshot`

`input_trace` 会拆开返回原始文本、结构化证据、自然语言解析结果、合并后的证据映射，便于前端调试“为什么这个岗位被推荐出来”。
`input_trace` 里会额外返回 `resolved_target_role`，方便前端确认目标岗位最终命中了图谱里的哪个节点。
`target_role_analysis` 里会附带目标岗位路径、覆盖度、优势项和缺口项，方便前端直接做“我离目标岗位还差什么”的展示。
`bridge_recommendations` 也会返回图路径，不再只是孤立节点名。

`role_options` 里的每一项都包含 `node_id`、`label` 和 `search_terms`，前端可以直接拿来做岗位选择器，不需要再自己处理空格或大小写归一化。

## 设计说明

- 这里没有引入额外第三方依赖，优先保证仓库里直接可跑。
- 图谱数据放在 `backend/data/seeds/`，词典放在 `backend/data/dictionaries/`。
- 当前实现偏向稳定可演示，后续如果要接真实数据源，只需要替换 seed 数据和解析规则，不需要推翻入口层。
