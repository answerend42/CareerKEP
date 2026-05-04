# Career KG 后端

这是 `Career KG` 的后端实现，目标是把用户画像转成知识图谱上的标准节点，然后做分数传播、职业排序、near miss 兜底、桥接推荐和目标岗位差距分析。

## 现在包含的内容

- 自然语言解析：把“会 Python、SQL、做过前端项目”这类输入映射成图谱节点。
- 结构化输入归一：把前端或脚本传来的节点分值统一到 `node_id -> score`。
- 图谱推理：按 DAG 拓扑序传播分值，支持 `supports / evidences / requires / prefers / inhibits`。
- 推荐编排：输出正式推荐、near miss、桥接建议、目标岗位分析和传播快照。
- 本地服务：提供 `GET /health` 和 `POST /api/recommend`。

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

接口：

- `GET /health`
- `POST /api/recommend`
- `POST /api/recommend` 需要带 `Content-Type: application/json`，否则返回 `415`
- `POST /api/recommend` 会把请求体解析错误返回 `400`，服务端内部异常返回 `500`

请求体示例：

```json
{
  "text": "我会 Python、SQL，做过前端项目，也比较擅长沟通",
  "target_role": "backend_engineer",
  "top_k": 5
}
```

其中 `evidence` 支持 `node_id` / `id`、`score`、`source`、`raw_text` 这几类字段，其他附加字段会被忽略；`evidence` 也可以是单个对象或列表，列表里的无效项会被跳过，方便前端和脚本自由携带调试信息。

返回中包含：

- `recommendations`
- `near_miss_roles`
- `bridge_recommendations`
- `target_role_analysis`
- `propagation_snapshot`
- `graph_snapshot`

## 设计说明

- 这里没有引入额外第三方依赖，优先保证仓库里直接可跑。
- 图谱数据放在 `backend/data/seeds/`，词典放在 `backend/data/dictionaries/`。
- 当前实现偏向稳定可演示，后续如果要接真实数据源，只需要替换 seed 数据和解析规则，不需要推翻入口层。
