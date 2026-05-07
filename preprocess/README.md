# 预处理模块

本目录负责“原始数据收集 -> 实体抽取 -> 实体消歧 -> 结果落盘”的完整预处理流程。

## 目录职责

- `collector.py`：读取 `raw_sources/` 下的原始数据快照，统一成 `RawDocument`
- `catalog.py`：加载图谱种子节点与别名词典，构建实体目录
- `extractor.py`：在原始文本里寻找别名命中，并生成实体候选
- `disambiguator.py`：结合标题、上下文与实体层级，对候选实体做消歧
- `pipeline.py`：串联全流程并输出结构化结果

## 支持的输入格式

当前采集器支持以下原始数据格式：

- `json`
- `jsonl`
- `csv`
- `tsv`
- `txt`
- `md`

采集器会递归扫描 `raw_sources/` 目录，自动把不同格式的数据统一成标准文档结构。

## 输出文件

默认会写入 `preprocess/output/`，包含以下文件：

- `documents.json`：标准化后的原始文档快照
- `source_manifest.json`：原始数据扫描清单，包含已加载和被跳过的文件
- `mentions.json`：每一条实体命中记录
- `entities.json`：按实体聚合后的统计结果
- `disambiguation_review.json`：低置信度命中复核清单
- `entity_coverage.json`：实体覆盖率报告
- `summary.json`：整体运行摘要

## 运行方式

在仓库根目录执行：

```bash
python3 -m preprocess --input-dir preprocess/raw_sources --output-dir preprocess/output --review-threshold 0.98
```

如果不传参数，默认读取 `preprocess/raw_sources/`，并写入 `preprocess/output/`。

## 设计说明

- 采集阶段会对 `doc_id` 做唯一性校验，避免不同来源的文档在后续统计中互相覆盖。
- 采集阶段会额外输出原始数据清单，显式记录被跳过的文件，避免数据源里有文件但流水线完全不知道。
- 抽取阶段优先匹配长别名，再补充词干型生成别名，减少短词噪声。
- 抽取阶段会把标题、正文和结构化元数据一起纳入搜索语料，尽量不漏掉藏在标题里的关键信息。
- 消歧阶段会综合标题命中、正文命中、元数据上下文和实体层级先验，避免同名实体随机落点。
- 复核阶段会把低于阈值的命中单独输出，方便人工检查和继续补词典。

## 后续扩展建议

- 如果后面接入真实爬虫，可以直接把爬虫导出的快照放进 `raw_sources/`
- 如果图谱实体继续扩充，只需要同步更新后端的种子节点和别名词典，预处理会自动跟进
