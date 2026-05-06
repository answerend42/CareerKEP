# 图谱数据流水线

这个目录只负责 `data/` 内的知识图谱数据构建，不碰 `preprocess/`、`backend/`、`frontend/`。

## 输入

- `input/sample_entities.json`
  - 预处理阶段输出的实体集合。
- `input/sample_evidence.json`
  - 句子级原始证据，用来做关系抽取。
- `config/relation_schema.json`
  - 关系类型定义，约束 source/target 类型组合。
- `config/weight_rules.json`
  - 边权重计算规则。

## 输出

- `output/nodes.json`
  - 节点层数据，直接给后续图构建或推荐模块使用。
- `output/relation_instances.json`
  - 证据级关系实例，便于追溯每条边来自哪条句子。
- `output/edges.json`
  - 聚合后的边数据，包含权重、命中证据和关键词。
- `output/relation_summary.json`
  - 关系统计汇总，用于快速检查抽取结果是否合理。
- `output/extraction_log.json`
  - 运行日志与计数信息，便于调试和复核。

## 构建原则

1. 先规范实体，再抽取关系实例。
2. 关系抽取优先看实体类型，再看关键词命中。
3. 边权重综合基础权重、证据数量和实体置信度。
4. 输出格式尽量稳定，方便 backend 直接消费。

## 运行命令

```powershell
python scripts/build_kg_data.py
```

