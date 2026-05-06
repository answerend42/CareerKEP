# data 模块说明

`data/` 目录负责承接 `preprocess` 阶段产出的实体与原始文本，完成关系抽取、权重定性、图谱数据沉淀，并输出给后续 `backend` 使用的稳定输入文件。

## 当前约定

### 输入

- `input/sample_entities.json`
  - 规范化后的实体列表，来自 `preprocess` 阶段。
- `input/sample_evidence.json`
  - 原始文本证据或句子级语料，用于关系抽取。

### 输出

- `output/nodes.json`
  - 图谱节点，去重后的实体集合。
- `output/edges.json`
  - 图谱边，包含关系类型、证据与权重。
- `output/relation_summary.json`
  - 关系统计摘要，便于检查抽取质量。
- `output/extraction_log.json`
  - 抽取过程日志，便于排查规则命中情况。

## 使用方式

在 `data/` 目录下运行：

```powershell
python scripts/build_kg_data.py
```

默认会读取 `input/` 下的示例数据，并生成 `output/` 下的图谱结果。

也可以显式指定输入文件：

```powershell
python scripts/build_kg_data.py --entities input/sample_entities.json --evidence input/sample_evidence.json --output-dir output
```

## 处理思路

1. 先将实体统一规范成节点。
2. 再基于句子中的实体共现和关键词规则抽取候选关系。
3. 最后按关系类型、证据数量、实体置信度计算边权值。

## 关系设计原则

- 关系类型尽量少而稳定，避免后续图传播时语义发散。
- 关系权重优先反映“是否强相关”，再反映“证据覆盖度”。
- 预处理产物不完整时，允许先用示例数据和规则管线占位，但输出格式要保持稳定。

