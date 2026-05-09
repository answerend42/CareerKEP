# data 模块快速上手

`data/` 负责承接 `preprocess/` 阶段输出的实体与原始证据，完成关系抽取、边权聚合、图索引构建，并把 backend 可以直接消费的图谱数据沉淀到 `output/`。

## 推荐流程

先一键构建，再做校验：

```powershell
python scripts/rebuild_and_validate.py
```

如果只想单独构建或单独校验，也可以这样运行：

```powershell
python scripts/build_kg_data.py --entities input/sample_entities.json --evidence input/sample_evidence.json --output-dir output
python scripts/validate_kg_data.py --output-dir output
```

如果要对比两次构建结果，可以使用：

```powershell
python scripts/compare_kg_catalog.py --left-dir output --right-dir output
```

## 核心输出

- `output/nodes.json`
  - 去重后的实体节点。
- `output/relation_instances.json`
  - 句子级关系实例，保留原始证据和命中的关键词。
- `output/relation_candidates.json`
  - 候选关系轨迹，记录最终选择了哪一条关系，以及为什么选中。
- `output/edges.json`
  - 聚合后的图谱边，包含权重、证据数和关键词集合。
- `output/relation_catalog.json`
  - 关系目录，汇总关系类型、关键词分组和覆盖情况。
- `output/relation_matrix.json`
  - 按实体类型对关系做矩阵化汇总，便于后续传播逻辑直接使用。
- `output/graph_index.json`
  - 图索引，包含邻接表和按实体类型、关系类型划分的索引。
- `output/graph_quality.json`
  - 图谱质量报告，记录孤立节点、度分布和覆盖率。
- `output/career_profiles.json`
  - 职业画像，聚合职业的技能、工具、学历、特质和相关岗位。
- `output/recommendation_index.json`
  - 反向推荐索引，便于根据目标实体召回职业。
- `output/entity_lookup.json`
  - 实体查找索引，按职业画像和推荐结果做快速定位。
- `output/node_lookup.json`
  - 节点查询索引，支持按 ID、名称、别名和类型查找。
- `output/relation_summary.json`
  - 关系统计摘要，适合快速查看抽取是否正常。
- `output/extraction_log.json`
  - 构建日志和输入文件追踪信息。
- `output/graph_manifest.json`
  - 构建清单，记录输入来源和输出文件列表。
- `output/graph_contract.json`
  - 机器可读图谱契约，backend 可据此核对输出边界和约束。
- `output/data_catalog.json`
  - 输出目录清单，记录每个产物的大小和 SHA256。

## 维护要点

- 关系类型尽量少而稳定，避免图传播放大歧义。
- 新增关键词优先补到 `config/`，不要把规则散落在脚本里。
- 输出字段尽量保持稳定，新增字段优先追加，不要随意改名。
- 若要比较两次构建，优先看 `compare_kg_catalog.py` 的结果，它已经把 `graph_contract.json` 纳入稳定比对。
