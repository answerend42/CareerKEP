# preprocess

这里维护职业推荐系统的预处理流水线，目标是把原始文本快照整理成统一的实体目录和抽取结果。

## 本轮实现

- 读取仓库现有的 seed 节点和 alias 词典，构建与后端图谱一致的实体 catalog。
- 从 `preprocess/raw_sources/` 加载原始文档快照。
- 对原始文本做实体抽取。
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
- `mentions.json`：每条实体命中的抽取结果。
- `entities.json`：按实体汇总后的统计结果。
- `summary.json`：这次预处理的整体统计信息。

## 设计说明

1. 先读取 seed 图谱中的节点和别名。
2. 再对原始文本进行宽松匹配，先收集候选，再统一消歧。
3. 对 `后端`、`前端`、`数据`、`机器学习` 这类容易出现歧义的表达，优先结合上下文词做判断。
4. 抽取结果尽量保留中文语义，方便后续继续做图谱构建。

## 后续扩展

- 把 `preprocess/raw_sources/` 替换为真实爬虫、API 拉取或人工整理的原始快照。
- 增加更细粒度的实体类型，例如技术栈、课程、证书和行业标签。
- 补充更严格的评估脚本，用于检查抽取覆盖率和消歧准确率。
