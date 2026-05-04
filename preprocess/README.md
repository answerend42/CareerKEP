# preprocess

这里维护职业推荐系统的预处理流水线，目标是把原始文本快照整理成统一的实体目录和抽取结果。

## 本轮实现

- 读取仓库现有的 seed 节点和 alias 词典，构建与后端图谱一致的实体 catalog。
- 从 `preprocess/raw_sources/` 递归加载原始文档快照，支持 `json`、`jsonl`、`csv`、`tsv`、`txt` 和 `md`。
- 对原始文本做实体抽取，保留每一次命中位置与上下文。
- 对同一别名可能对应多个实体的情况做消歧。
- 导出 `documents.json`、`mentions.json`、`entities.json` 和 `summary.json`。

## 运行方式

```bash
python3 -m preprocess.pipeline
```

默认输入目录：

- `preprocess/raw_sources/`

默认输出目录：

- `preprocess/output/`

也可以显式指定路径：

```bash
python3 -m preprocess.pipeline --input-dir preprocess/raw_sources --output-dir preprocess/output
```

## 输出说明

- `documents.json`：采集到的原始文档快照。
- `mentions.json`：每条实体命中的抽取结果，包含 `span_start`、`span_end` 和 `context`。
- `entities.json`：按实体汇总后的统计结果。
- `summary.json`：这次预处理的整体统计信息，包含文档数、命中数、覆盖实体数和平均命中数。

## 原始数据格式

采集器会把不同来源的数据归一成统一的文档对象，常用字段优先级如下：

- 文档编号：`doc_id` -> `id`
- 来源：`source` -> `origin`
- 标题：`title` -> `name` -> `heading`
- 正文：`text` -> `content` -> `body` -> `description` -> `summary`
- 兜底正文：`url` 或 `link`

这意味着你可以把爬虫导出的结果、人工整理的表格、JSON 快照按目录直接放进 `preprocess/raw_sources/`，管线会自动读取。

## 设计说明

1. 先读取 seed 图谱中的节点和别名。
2. 再对原始文本按别名长度优先进行匹配，先收集候选，再统一消歧。
3. 对 `后端`、`前端`、`数据`、`机器学习` 这类容易出现歧义的表达，优先结合上下文词做判断。
4. 抽取结果尽量保留中文语义和原始上下文，方便后续继续做图谱构建。

## 自检建议

如果要快速确认抽取逻辑是否正常，可以直接运行：

```bash
python3 -m preprocess.pipeline --input-dir preprocess/raw_sources --output-dir preprocess/output
```

或者用 `python3 -m unittest discover preprocess/tests` 检查抽取和流水线的基础行为。

## 后续扩展

- 把 `preprocess/raw_sources/` 替换为真实爬虫、API 拉取或人工整理的原始快照。
- 增加更细粒度的实体类型，例如技术栈、课程、证书和行业标签。
- 补充更严格的评估脚本，用于检查抽取覆盖率和消歧准确率。
