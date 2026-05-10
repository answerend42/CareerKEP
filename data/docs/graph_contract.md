# 图谱契约说明

`output/graph_contract.json` 是 `data/` 模块面向后端的机读契约文件，目标是把关系类型、权重规则、构图健康度和输出文件职责集中到一个入口里，减少后端对多个 JSON 的分散依赖。

## 文件内容

- `contract_version`
  - 契约版本，当前为 `1.0`。
- `generated_at`
  - 构建时间，使用 UTC 时间戳。
- `allowed_entity_types`
  - 当前允许的实体类型集合，和构图脚本保持一致。
- `source_files`
  - 输入文件的路径、大小和 SHA256，便于追溯构建来源。
- `weight_rules`
  - 当前边权计算规则，和 `config/weight_rules.json` 保持同步。
- `relation_catalog_summary`
  - 关系类型总览，包括已命中、未命中和覆盖率摘要。
- `relation_types`
  - 逐条列出关系类型定义、关键词组、覆盖情况和权重范围。
- `relation_matrix_summary`
  - 按实体类型对统计出来的关系矩阵摘要，适合后端做类型传播入口。
- `graph_health`
  - 图谱质量信息，包括节点数、边数、连通情况和节点类型覆盖率。
- `output_files`
  - 本轮构建会生成的全部输出文件及其职责说明。

## 使用建议

- 后端优先读取 `graph_contract.json`，再按需打开 `relation_catalog.json`、`relation_matrix.json`、`graph_index.json` 等细分文件。
- 需要检查构建是否完整时，先比对 `graph_contract.json.output_files` 和 `output/` 目录实际文件，再看 `data_catalog.json`。
- 需要调权时，优先改 `config/weight_rules.json`，再用 `build_kg_data.py` 重新生成契约和输出。

## 当前定位

- `graph_manifest.json` 偏向“构建过程清单”。
- `graph_contract.json` 偏向“后端消费契约”。
- `data_catalog.json` 偏向“文件级清单与校验摘要”。

