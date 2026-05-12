# preprocess 预处理说明

这个目录负责职业推荐系统的预处理链路，目标是把原始数据整理成可供知识图谱使用的标准实体与命中结果。

## 功能

1. 原始数据收集
2. 实体抽取
3. 实体消歧
4. 预处理结果导出

## 入口

### 命令行

```bash
python3 -m preprocess --input-dir preprocess/raw_sources --output-dir preprocess/output
```

参数说明：

- `--input-dir`：原始数据目录，默认读取 `preprocess/raw_sources/`
- `--output-dir`：输出目录，默认写入 `preprocess/output/`
- `--review-threshold`：消歧复核阈值，低于该分数的命中会写入复核清单

### Python 调用

```python
from preprocess import collect_source_manifest, load_raw_documents, load_entity_catalog, extract_mentions, run_pipeline

manifest = collect_source_manifest()
documents = load_raw_documents()
result = run_pipeline()
```

## 支持的原始数据格式

当前采集器支持以下文件：

- `json`
- `jsonl`
- `csv`
- `tsv`
- `txt`
- `md`
- `html`
- `htm`

### 采集规则

- 会递归扫描 `input_dir` 下的所有子目录
- 会保留每个文件的 `source_path`、`source_format`
- 会记录不支持的文件、空文件和解析错误
- 会检查 `doc_id` 是否重复，避免后续实体统计串文档

## 实体抽取思路

抽取阶段会把一篇文档里的以下内容一起纳入搜索范围：

- 标题
- 正文
- `metadata` 中的补充字段
- `extra` 中的补充字段

抽取时会优先匹配更长、更可信的别名，再把结果交给消歧模块排序。

## 消歧思路

消歧阶段对候选实体进行打分，主要参考：

- 别名来源可信度
- 标题是否命中
- 正文是否命中
- 实体层级先验
- 上下文提示词

当同一个别名对应多个实体时，会输出完整的候选排序和分差，方便后续人工检查。

## 输出文件

预处理运行后会在 `output_dir` 下生成：

- `documents.json`：标准化后的原始文档
- `source_manifest.json`：原始文件清单
- `mentions.json`：所有实体命中记录
- `entity_catalog.json`：实体目录快照
- `alias_index.json`：别名反向索引
- `document_entities.json`：按文档汇总的实体结果
- `entity_documents.json`：按实体展开的文档结果
- `entities.json`：实体级汇总
- `disambiguation_review.json`：低置信度复核清单
- `disambiguation_trace.json`：歧义样本轨迹
- `alias_ambiguity.json`：别名歧义统计
- `stage_summary.json`：采集、抽取、消歧和覆盖的阶段摘要
- `entity_coverage.json`：实体覆盖率统计
- `uncovered_entities.json`：未覆盖实体明细
- `uncovered_entity_candidates.json`：未覆盖实体的补词典候选
- `summary.json`：整体统计摘要

## 目录约定

- `raw_sources/`：原始输入样例或快照
- `output/`：预处理产物
- `tests/`：预处理相关测试

## 开发注意事项

- 只在 `preprocess/` 下维护预处理相关实现
- 新增数据格式时，优先补采集器，再补抽取器和测试
- 消歧规则变更后，要同步检查输出清单是否还能解释结果
- 如果原始数据结构变化较大，优先统一升级解析逻辑，不要同时保留多套分叉入口
- `summary.json` 偏向整体统计，`stage_summary.json` 偏向按阶段排查问题，二者一起看更容易定位覆盖缺口
