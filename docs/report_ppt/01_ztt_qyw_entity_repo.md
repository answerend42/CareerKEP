# ztt & qyw：数据获取、清洗与实体仓库扩容

对应分支：`entityRepo`
主要目录：`optimize/`

## 一句话定位

这个分支负责从外部数据中获取更多职业领域实体和别名，重点不是直接改线上图谱，而是构建一个可审阅、可消歧、可链接的“实体仓库”。

用课程术语说，它主要覆盖：

```text
知识获取 -> 信息抽取 -> 实体识别 -> 实体消歧 -> 实体链接/知识融合材料
```

## 与课件知识点的对应

| 课件知识点 | 分支里的实现 |
| --- | --- |
| 第 4 章：知识获取 | 从 JD、简历、CN_skillspan、ESCO、O*NET 获取领域数据 |
| 第 4 章：信息抽取 | 清洗文本、分句、抽取 mention 和候选词面 |
| 第 4 章：命名实体识别 / 细粒度实体分类 | 区分 skill、tool、language、knowledge、project、interest、soft_skill、constraint |
| 第 5 章：实体消歧 | 字符串归一化、embedding 相似度、DBSCAN 聚类、review queue |
| 第 5 章：实体链接 | 把不同词面、别名和候选实体对齐到已有图谱节点 |
| 第 3 章：知识融合 | 与 ESCO/O*NET 等外部标准做对齐，形成 external refs |

## 输入数据

`entityRepo` 的数据来源覆盖了结构化、半结构化和非结构化数据，正好对应课件第 4 章中“信息抽取来源”的分类。

| 来源 | 类型 | 作用 |
| --- | --- | --- |
| FairCV 简历数据 | 非结构化/半结构化文本 | 从真实简历中发现技能、工具、项目经历和软技能表达 |
| JD 招聘文本 | 非结构化/半结构化文本 | 从岗位要求中发现职业技能、工具和能力要求 |
| CN_skillspan | 标注语料/训练数据 | 辅助技能识别和规则评测 |
| ESCO | 外部职业技能标准 | 给内部实体增加外部标准引用 |
| O*NET | 外部职业能力标准 | 给岗位、技能、工具做外部对齐 |
| 原项目 `data/` | seed 知识库 | 作为已有实体和别名的对齐目标 |

## 处理流水线

### 1. 数据采集

相关代码：

- `optimize/data_collection/fetch_fairCV.py`
- `optimize/data_collection/crawl_jd.py`
- `optimize/data_collection/import_skillspan_jd.py`
- `optimize/data_collection/fetch_external_standards.py`
- `optimize/data_collection/catalog.py`

这一层对应课件里的“知识获取”。它把外部数据统一收集到 `optimize/pipeline_data/raw/`，并维护数据源目录。

### 2. 清洗与分句

相关代码：

- `optimize/staging/clean_documents.py`
- `optimize/staging/segment_sentences.py`

作用：

- 去除噪声文本。
- 对简历/JD 做章节切分。
- 对句子生成偏移位置，方便后续 mention 定位。
- 统一输出 `staged_documents.jsonl`。

当前材料中有 `1,288` 份 staged 文档：

| source | 文档数 |
| --- | ---: |
| cn_skillspan_lkst | 82 |
| csv_import | 506 |
| fairCV | 700 |

### 3. 实体识别与候选词面挖掘

相关代码：

- `optimize/ner/rule_ner.py`
- `optimize/ner/distant_supervision.py`
- `optimize/ner/llm_ner.py`
- `optimize/ner/merge_mentions.py`
- `optimize/ner/abbr_expansion.json`

采用了多路实体识别：

| 方法 | 作用 |
| --- | --- |
| 规则 NER | 用已有 alias、正则和缩写表识别确定性较强的实体 |
| 远程监督 | 根据已有图谱和词面共现发现候选实体 |
| LLM NER | 对规则难覆盖的文本做结构化抽取 |
| mention 合并 | 合并重复 mention，并融合置信度 |

从课程术语看，这一层是“命名实体识别”和“开放域实体识别”的项目化实现。

### 4. 实体消歧与聚类

相关代码：

- `optimize/disambiguation/string_normalize.py`
- `optimize/disambiguation/embedding_disambiguate.py`

处理逻辑：

1. 先做字符串归一化和精确匹配。
2. 再用 embedding 相似度找可能指向同一实体的候选。
3. 用 DBSCAN 聚类得到新实体簇。
4. 把不确定项写入 review queue，等待人工确认。

这对应课件第 5 章的两个核心问题：

- 同一实体有不同表达，例如 `SQL Server`、`sqlserver`、`ms sqlserver`。
- 同一词面可能对应不同实体，需要上下文和聚类判断。

### 5. 外部标准对齐

相关代码：

- `optimize/external_align/align_esco_onet.py`

作用：

- 把内部实体对齐到 ESCO/O*NET。
- 为实体添加 external refs。
- 让图谱不只是项目内部自定义词表，而能连接到外部职业标准。

这可以在 PPT 中称为“知识融合”或“外部知识库对齐”。

### 6. 输出与质量评估

相关代码：

- `optimize/output/generate_output.py`
- `optimize/evaluation/validate_entity_quality.py`
- `optimize/evaluation/coverage_report.py`
- `optimize/evaluation/case_report.py`
- `optimize/evaluation/review_queue.py`

输出文件：

| 文件 | 用途 |
| --- | --- |
| `optimize/output/skills_enriched.json` | 待审阅的实体扩展结果 |
| `optimize/output/aliases_enriched.json` | 待审阅的别名扩展结果 |
| `optimize/output/imported_profiles_new.json` | 待追加的 profile |
| `optimize/pipeline_data/canonical/entity_quality_report.json` | 实体质量校验报告 |
| `optimize/pipeline_data/canonical/entity_cooccurrence_candidates.jsonl` | 关系预测可用的实体共现候选 |

## 主要产物和数量

根据分支产物和当前整合材料，`entityRepo` 提供了：

| 产物 | 数量 | 说明 |
| --- | ---: | --- |
| staged 文档 | 1,288 | 已清洗的简历/JD/SkillSpan 文档 |
| mentions | 83 | 已识别并可用于实体链接的 mention |
| entityRepo 实体 | 173 | enriched 实体仓库规模 |
| extracted 新实体 | 14 | 从数据中抽取出的待审实体 |
| unique aliases | 490 | 质量报告中的唯一别名数 |
| external refs | 59 | ESCO/O*NET 对齐引用 |
| new entity clusters | 45 clusters | embedding 聚类出的新实体候选 |
| disambiguation review rows | 1,241 | 消歧待复核材料 |
| cooccurrence candidates | 2,666 | 原始实体共现关系候选 |

整合后的 `data/entity_linking_materials/summary.json` 还显示，加入 runtime 图谱材料后可形成 `2,784` 行 relation candidate inputs，用于后续关系预测或人工复核。

## 对最终图谱的贡献

这个分支对最终图谱的贡献主要是“候选材料”和“链接材料”，而不是直接替换线上图谱。

具体来说：

1. 提供更多实体候选：例如 HTML、SpringMVC、Hibernate、SpringCloud、OpenStack 等。
2. 提供更多别名：例如 SQL、沟通能力、团队合作、系统架构设计等都有多种中文表达。
3. 提供外部标准引用：可以把内部节点和 ESCO/O*NET 连接起来。
4. 提供实体链接 review queue：帮助判断哪些候选能链接到已有 365 个节点，哪些应该成为新增节点。
5. 提供共现候选：为后续关系抽取提供召回材料。

## 为什么不能直接全部入图

entityRepo 的很多输出是候选，不是最终事实。例如分支里有一些聚类明显需要人工审核：

- `tool_lstm` 聚到了 `lnmp`。
- `tool_ps` 聚到了 `ssh`。
- `tool_openstack` 聚到了 `opengl/openshift/openflow`。

这正好可以作为汇报中的质量控制点：信息抽取会带来噪声，所以必须经过实体消歧、人工复核和质量门禁，才能进入正式知识库。

## PPT 可讲重点

可以用下面的话概括这部分：

> ztt & qyw 负责把外部数据变成可入图的实体候选。他们不是直接改图谱，而是先做数据采集、清洗、NER、消歧和外部标准对齐，形成一个实体仓库。这个仓库为下一步实体链接和关系抽取提供了候选实体、别名、mention、共现关系和 review queue。

适合展示的图：

```text
JD/简历/SkillSpan/ESCO/O*NET
        -> 清洗分句
        -> 规则 NER + 远程监督 + LLM NER
        -> 字符串归一 + embedding 消歧
        -> enriched entities / aliases / external refs / review queue
```
