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
- `html`
- `htm`

采集器会递归扫描 `raw_sources/` 目录，自动把不同格式的数据统一成标准文档结构。

## 输出文件

默认会写入 `preprocess/output/`，包含以下文件：

- `documents.json`：标准化后的原始文档快照
- `source_manifest.json`：原始数据扫描清单，包含已加载和被跳过的文件
- `mentions.json`：每一条实体命中记录
- `entity_catalog.json`：完整实体目录快照，保留实体标签、层级、别名和别名来源
- `alias_index.json`：反向别名索引，展开每个别名会命中的候选实体，便于排查冲突和补词典
- `disambiguation_trace.json`：消歧轨迹，只保留发生歧义的命中，记录候选排序和分差
- `document_entities.json`：按文档聚合的实体摘要，便于快速查看每篇原始文档抽到了哪些实体
- `entity_documents.json`：按实体展开到文档维度的关联报告，便于分析实体分布和覆盖率
- `entities.json`：按实体聚合后的统计结果
- `uncovered_entities.json`：未被任何原始语料覆盖的实体明细，带别名和别名来源
- `uncovered_entity_candidates.json`：未覆盖实体的补词典候选，按优先级排序推荐先补哪些别名
- `disambiguation_review.json`：低置信度命中复核清单
- `entity_coverage.json`：实体覆盖率报告
- `summary.json`：整体运行摘要
  - 额外包含 `format_stats`，用于查看各类输入文件的加载、跳过和异常分布

## 运行方式

在仓库根目录执行：

```bash
python3 -m preprocess --input-dir preprocess/raw_sources --output-dir preprocess/output --review-threshold 0.98
```

如果不传参数，默认读取 `preprocess/raw_sources/`，并写入 `preprocess/output/`。

建议先用这个命令跑通一轮，再根据 `preprocess/output/summary.json` 和 `preprocess/output/disambiguation_review.json` 调整原始数据和别名词典。

## 设计说明

- 采集阶段会对 `doc_id` 做唯一性校验，避免不同来源的文档在后续统计中互相覆盖。
- 采集阶段会额外输出原始数据清单，显式记录被跳过的文件，避免数据源里有文件但流水线完全不知道。
- 采集阶段会自动拆解常见的多层 JSON 套壳结构，兼容 `response/data/results/items` 这类接口快照。
- 采集阶段会容忍 JSONL 中的局部坏行，能读多少算多少，并在清单里记录错误行信息和坏行总数。
- 抽取阶段优先匹配长别名，再补充词干型生成别名，减少短词噪声。
- 抽取阶段会避免把压缩后只剩单字符的别名拿去做模糊匹配，防止 `C++` 之类的实体被误缩成普通单字母噪声。
- 抽取阶段会把标题、正文和结构化元数据一起纳入搜索语料，尽量不漏掉藏在标题里的关键信息。
- 消歧阶段会综合标题命中、正文命中、元数据上下文和实体层级先验，避免同名实体随机落点。
- 复核阶段会把低于阈值的命中单独输出，方便人工检查和继续补词典。

## 输出字段说明

- `summary.json`：用于快速确认这次预处理是否成功，包含文档数、命中数、覆盖数、别名索引统计、消歧歧义统计、错误文件数和输出目录。
- `source_manifest.json`：用于排查原始数据扫描情况，记录每个文件的状态、格式、错误行与跳过原因。
- `entity_catalog.json`：用于核对当前实体词典是否完整，包含实体 ID、标签、层级、别名和别名来源。
- `alias_index.json`：用于检查别名歧义和覆盖盲区，适合人工补充别名和调整消歧规则。
- `disambiguation_trace.json`：用于复核同一别名的候选实体排序、次优分差和近似平局样本。
- `uncovered_entities.json`：用于直接查看未覆盖实体及其别名来源，方便补语料和补词典。
- `uncovered_entity_candidates.json`：用于查看未覆盖实体的推荐别名补充顺序和优先级分数。
- `document_entities.json`：用于按文档抽查抽取效果，适合人工浏览某篇原始数据抽到了哪些实体。
- `entity_documents.json`：用于按实体查看覆盖文档，适合分析某个实体在语料中的分布。
- `disambiguation_review.json`：用于后续补词典和调权，专门收集低置信度命中。

## 后续扩展建议

- 如果后面接入真实爬虫，可以直接把爬虫导出的快照放进 `raw_sources/`
- 如果图谱实体继续扩充，只需要同步更新后端的种子节点和别名词典，预处理会自动跟进
