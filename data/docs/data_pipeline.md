# data 模块数据流水线

本文档只描述 `data/` 目录内部的数据构建流程，目标是为知识图谱推荐模块提供稳定、可追溯、可直接消费的输入。

## 目录职责

- `input/`
  - 存放 `preprocess` 阶段输出的实体和原始证据样例。
- `config/`
  - 存放关系类型、关键词规则和权重规则。
- `scripts/`
  - 存放图谱构建、校验和目录比较脚本。
- `output/`
  - 存放构建后的标准化图谱数据和索引。

## 构建步骤

1. 读取 `input/sample_entities.json`，统一实体结构并去重。
2. 读取 `input/sample_evidence.json`，根据实体名和别名做长词优先匹配。
3. 结合 `config/relation_keywords.json` 和 `config/relation_schema.json` 抽取关系实例，并优先选择更靠近目标实体的关系关键词。
4. 结合 `config/weight_rules.json` 计算边权重。
5. 输出以下构建产物：
   - `output/nodes.json`
   - `output/relation_instances.json`
   - `output/relation_candidates.json`
     - 候选轨迹，记录选中的关系、目标邻近度分数和结构化选择因子，便于追踪抽取决策。
   - `output/edges.json`
   - `output/relation_catalog.json`
     - 关系目录，把关系类型定义、关键词分组和当前证据覆盖情况放在一起，便于调参和排查漏抽。
     - 其中的 `coverage_summary` 和 `unobserved_relation_types` 可直接用来定位还没命中的关系类型。
   - `output/graph_index.json`
   - `output/graph_quality.json`
   - `output/career_profiles.json`
   - `output/recommendation_index.json`
   - `output/entity_lookup.json`
   - `output/relation_summary.json`
   - `output/extraction_log.json`
   - `output/data_catalog.json`
   - `output/graph_manifest.json`

## 关键设计

- 关系类型与实体类型绑定，避免无约束扩散。
- 关键词规则和关系 schema 分离，方便后续扩展抽取逻辑。
- 权重优先体现“是否相关”，再体现证据覆盖和实体置信度。
- 图索引按节点类型和边方向组织，便于后续传播算法直接读取。
- 职业画像把职业出边整理成可直接用于推荐的结构，减少 backend 的重复聚合工作。
- 反向推荐索引把目标要素映射回职业，适合做召回层输入。
- `entity_lookup.json` 把职业画像和反向推荐索引整理成按 ID 可直接查询的映射，适合 backend 做快速查找。
- 构建清单和目录文件记录输入来源、输出文件和 SHA256，方便版本对比和完整性检查。

## 运行建议

在 `data/` 目录下先运行构建，再运行校验：

```powershell
python scripts/build_kg_data.py
python scripts/validate_kg_data.py
```

如果需要比较两次构建结果，可以运行：

```powershell
python scripts/compare_kg_catalog.py --left-dir output --right-dir output
```
