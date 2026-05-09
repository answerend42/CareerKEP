# data 模块快速开始

这个目录只负责知识图谱数据，不碰 `preprocess/`、`backend/`、`frontend/`。

## 推荐流程

先一键构建，再做校验：

```powershell
python scripts/rebuild_and_validate.py
```

如果需要单独构建或指定输入，可以这样写：

```powershell
python scripts/build_kg_data.py --entities input/sample_entities.json --evidence input/sample_evidence.json --output-dir output
```

```powershell
python scripts/validate_kg_data.py --output-dir output
```

## 主要输出

- `output/nodes.json`
  - 去重后的实体节点。
- `output/relation_instances.json`
  - 句子级关系实例，保留原始证据和命中的关键词。
- `output/relation_candidates.json`
  - 候选轨迹，记录最终关系为什么被选中，并保留目标邻近度分数。
- `output/edges.json`
  - 聚合后的图谱边，包含权重和证据数。
- `output/relation_catalog.json`
  - 关系目录，汇总关系类型、关键词分组和当前证据覆盖，方便后续调参。
- `output/graph_index.json`
  - 按节点和关系整理的索引，便于 backend 直接消费。
- `output/graph_quality.json`
  - 节点覆盖、孤立点和度分布摘要。
- `output/career_profiles.json`
  - 职业画像聚合结果。
- `output/recommendation_index.json`
  - 反向推荐索引，适合召回层使用。
- `output/entity_lookup.json`
  - 按 ID 直接查询的实体索引，减少后端扫描。
- `output/relation_summary.json`
  - 关系统计摘要。
- `output/extraction_log.json`
  - 构建日志和来源记录。
- `output/data_catalog.json`
  - 输出目录清单，记录大小和 SHA256。
- `output/graph_manifest.json`
  - 构建清单，记录输入来源和输出列表。

## 使用提醒

- 最终输出尽量保持字段稳定，方便 backend 直接读取。
- 新增字段优先追加，不要随意改名。
- 如果要排查抽取问题，先看 `relation_candidates.json`，再看 `edges.json` 和 `graph_quality.json`。
