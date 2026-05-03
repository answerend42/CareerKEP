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

### 2. 启动 HTTP 服务

```bash
python3 -m backend.app.main serve --host 127.0.0.1 --port 8000
```

### 3. 运行后端自测

```bash
python3 -m unittest discover -s backend/tests
```

接口：

- `GET /health`
- `POST /api/recommend`

请求体示例：

```json
{
  "text": "我会 Python、SQL，做过前端项目，也比较擅长沟通",
  "target_role": "backend_engineer",
  "top_k": 5
}
```

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
