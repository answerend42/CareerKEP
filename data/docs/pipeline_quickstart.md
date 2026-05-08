# data 模块快速说明

这个目录只负责知识图谱数据，不碰 `preprocess/`、`backend/`、`frontend/`。

## 目录职责

- `input/`
  - `preprocess` 阶段产出的实体和原始证据样例。
- `config/`
  - 关系类型、关键词规则和权重规则。
- `scripts/`
  - 图谱构建、校验和目录比较脚本。
- `output/`
  - 构建后的标准化图谱数据文件。
- `docs/`
  - data 模块内部说明文档。

## 推荐流程

先执行一键脚本，再看验证结果：

```powershell
python scripts/rebuild_and_validate.py
```

如果需要显式指定输入或输出路径，也可以传入参数：

```powershell
python scripts/rebuild_and_validate.py --entities input/sample_entities.json --evidence input/sample_evidence.json --output-dir output
```

## 输出文件

- `output/nodes.json`
  - 去重后的实体节点。
- `output/relation_instances.json`
  - 句子级关系实例，保留证据文本和匹配关键词。
- `output/edges.json`
  - 聚合后的图谱边，包含权重和证据数。
- `output/graph_index.json`
  - 按节点和关系整理的索引，便于 backend 直接消费。
- `output/graph_quality.json`
  - 节点覆盖、孤立点和度分布摘要。
- `output/career_profiles.json`
  - 职业画像聚合结果。
- `output/recommendation_index.json`
  - 反向推荐索引，适合召回层使用。
- `output/relation_summary.json`
  - 关系统计摘要。
- `output/extraction_log.json`
  - 构建日志和输入来源记录。
- `output/data_catalog.json`
  - 输出目录清单，记录大小和 SHA256。
- `output/graph_manifest.json`
  - 构建清单，记录输入来源和输出列表。

## 关系与权重原则

- 关系类型必须先在 `config/relation_schema.json` 中定义。
- 关键词命中只负责判定关系类型，不直接决定最终权重。
- 权重由基础权重、证据增量和实体置信度共同计算。
- 最终输出尽量保持字段稳定，方便 backend 直接读取。
