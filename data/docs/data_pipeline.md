# 数据流水线说明

本文档只描述 `data/` 目录内部的数据构建流程，目标是为知识图谱推荐模块提供稳定、可追溯的输入。

## 目录职责

- `input/`
  - 放置预处理阶段产出的实体和原始证据样例。
- `config/`
  - 放置关系类型、关键词规则和权重规则。
- `scripts/`
  - 放置图谱构建脚本。
- `output/`
  - 放置构建后的节点、边、关系实例和统计结果。

## 构建步骤

1. 读取 `input/sample_entities.json`，统一实体字段结构并去重。
2. 读取 `input/sample_evidence.json`，按实体名和别名做长词优先匹配。
3. 结合 `config/relation_keywords.json` 和 `config/relation_schema.json` 抽取关系实例。
4. 结合 `config/weight_rules.json` 计算边权重。
5. 输出 `output/nodes.json`、`output/relation_instances.json`、`output/edges.json`、`output/graph_index.json`、`output/graph_quality.json`、`output/career_profiles.json`、`output/relation_summary.json`、`output/extraction_log.json` 和 `output/graph_manifest.json`。

## 关系设计原则

- 关系类型必须和实体类型组合绑定，避免无约束扩散。
- 关键词规则和关系 schema 分离，便于后续扩充抽取逻辑。
- 权重计算优先体现“是否相关”，再体现“证据覆盖度”和“实体置信度”。
- 图索引优先按节点类型和边方向组织，方便后续传播算法直接读取。
- 构建清单会记录输入来源和输出文件，方便快速确认本轮产物是否完整。
- 质量报告会显式列出孤立节点和类型覆盖率，便于持续补齐 preprocess 产物。
- 职业画像会把职业出边整理成可直接用于推荐的结构，减少 backend 的重复聚合工作。

## 输出要求

- 节点、边、关系实例的字段名保持稳定。
- 所有输出文件均为 UTF-8 编码的 JSON。
- 新增字段尽量追加，不要随意替换已有字段。

## 运行建议

在 `data/` 目录下执行：

```powershell
python scripts/build_kg_data.py
```

如果要验证某一版输入，可以指定参数单独构建：

```powershell
python scripts/build_kg_data.py --entities input/sample_entities.json --evidence input/sample_evidence.json --schema config/relation_schema.json --keywords config/relation_keywords.json --rules config/weight_rules.json --output-dir output
```
