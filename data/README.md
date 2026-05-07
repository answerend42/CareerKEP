# data 模块说明

`data/` 目录负责承接 `preprocess` 阶段输出的实体与原始证据，完成关系抽取、权重计算和图谱数据沉淀，并把稳定的构图结果提供给后续 `backend` 使用。

## 当前输入

- `input/sample_entities.json`
  - 预处理阶段输出的实体列表，包含名称、别名、类型和置信度。
- `input/sample_evidence.json`
  - 句子级原始证据，用于关系抽取。
- `config/relation_schema.json`
  - 关系类型定义，约束 source / target 的实体类型组合。
- `config/relation_keywords.json`
  - 关系关键词规则，负责把证据中的关键词映射为具体关系类型。
- `config/weight_rules.json`
  - 边权重计算规则。

## 当前输出

- `output/nodes.json`
  - 去重后的实体节点。
- `output/relation_instances.json`
  - 证据级关系实例，保留原始证据和命中的关键词。
- `output/edges.json`
  - 聚合后的图谱边，包含权重、证据数和关键词。
- `output/graph_index.json`
  - 给 backend 直接使用的图索引，包含按类型归类的节点和邻接表。
- `output/graph_quality.json`
  - 图谱质量报告，记录孤立节点、覆盖率和度分布，方便检查数据完整性。
- `output/career_profiles.json`
  - 职业画像聚合结果，按职业整理技能、工具、学历、特质和相关岗位，便于推荐模块直接消费。
- `output/recommendation_index.json`
  - 反向推荐索引，按目标技能、工具、学历、特质或岗位聚合可推荐的职业，便于候选召回。
- `output/relation_summary.json`
  - 关系统计摘要，用于快速检查抽取结果。
- `output/extraction_log.json`
  - 构建日志与计数信息，便于调试和复核。
- `output/graph_manifest.json`
  - 图谱构建清单，记录输入来源和输出文件列表，给 backend 或人工检查使用。

## 使用方式

在 `data/` 目录下执行：

```powershell
python scripts/build_kg_data.py
```

也可以显式指定输入和输出：

```powershell
python scripts/build_kg_data.py --entities input/sample_entities.json --evidence input/sample_evidence.json --output-dir output
```

## 构建思路

1. 先统一实体结构，生成稳定的节点集合。
2. 再按实体名和别名在证据中做长词优先匹配，找到共现实体对。
3. 根据实体类型组合和关键词规则抽取关系实例。
4. 按关系类型、证据数和实体置信度计算边权重。
5. 最终输出节点、实例、边、图索引、质量报告、职业画像、反向推荐索引和统计清单，保证 backend 可以直接消费。

## 维护原则

- 关系类型尽量少而稳定，避免图传播阶段语义发散。
- 关键词规则单独放在 `config/`，方便后续补充新关系。
- 输出格式尽量稳定，新增字段优先追加，不随意改名。
