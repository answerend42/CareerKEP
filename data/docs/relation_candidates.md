# 关系候选轨迹说明

`output/relation_candidates.json` 是 `data/` 模块新增的中间产物，用来记录一次证据抽取中“为什么选中了这条关系”。

## 作用

- 保存实体对在原始证据中的命中结果。
- 同时记录正向和反向的候选关系，方便排查抽取方向是否合理。
- 让后续的权重调试、规则扩展和人工复核都有统一入口。

## 结构

每条记录对应一条最终关系实例，字段含义如下：

- `evidence_id`：证据编号。
- `evidence_source`：证据来源类型。
- `evidence_text`：原始证据文本。
- `pair_source_id` / `pair_target_id`：证据里按出现顺序提取出来的实体对。
- `source_id` / `target_id`：最终选中的关系方向。
- `relation_type`：最终选中的关系类型。
- `selected_direction`：`forward` 或 `reverse`。
- `matched_keywords`：最终命中的关键词。
- `forward_candidates`：正向候选列表。
- `reverse_candidates`：反向候选列表。

## 使用建议

- 当 `relation_instances.json` 和 `relation_candidates.json` 不一致时，优先检查候选轨迹里的 `forward_candidates` 和 `reverse_candidates`。
- 当某个职业的推荐结果不稳定时，先看 `relation_candidates.json`，再看 `edges.json` 和 `graph_quality.json`。
- 后续若要扩展更多关系类型，建议优先在这里补充候选轨迹的字段，而不是直接改最终边表。

