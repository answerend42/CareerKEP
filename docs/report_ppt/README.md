# CareerKEP 知识图谱工作总结文档

本目录用于后续报告 PPT。文档按小组分工拆分，并把实现内容对齐到老师课件里的知识工程术语。

## 文档索引

| 文件 | 对应分工 | 适合放进 PPT 的主题 |
| --- | --- | --- |
| `00_overview_and_course_alignment.md` | 全组总览 | 从数据到知识、KG 生命周期、课程知识点对齐 |
| `01_ztt_qyw_entity_repo.md` | ztt & qyw | 数据获取、清洗、实体识别、实体消歧、实体链接材料 |
| `02_lsy_ljc_seed_data_engine.md` | lsy & ljc | 基于 seed 图谱的自动扩容、语料抓取、候选生成、可回滚入图 |
| `03_sx_wxs_relation_design.md` | sx & wxs | 关系体系、DeepSeek 关系规划、置信度筛选、扩展图谱构建 |
| `04_jrh_syg_backend_inference.md` | jrh & syg | 输入归一、图上传播推理、core/aux 双通道、推荐解释 |
| `05_ppt_storyline_and_qna.md` | 汇报准备 | PPT 讲法、演示案例、老师可能追问与回答 |

## 当前最终图谱状态

当前 main 中保留的是经过清洗的扩展图谱：

| 指标 | 数量 |
| --- | ---: |
| 原始 seed 图谱节点 | 365 |
| 扩展后节点 | 398 |
| 新增节点 | 33 |
| 原始 seed 边 | 1,053 |
| 清洗后全量审阅边 | 3,395 |
| 保留的 LLM 边 | 2,342 |
| 排除的 very-low LLM 边 | 20 |

运行时推理不再把所有 LLM 边等价地当成正式评分事实。后端会把边编译为 `core`、`aux`、`similarity`、`explain` 通道：`core` 负责正式推荐判断，`aux` 负责候选发现、near miss、bridge 和补齐建议。

## 统一术语

后续汇报建议统一使用下面的课程术语：

| 课程术语 | 本项目对应实现 |
| --- | --- |
| 知识获取 | 从 JD、简历、SkillSpan、GitHub、roadmap、Wikipedia、O*NET/ESCO 获取职业领域数据 |
| 信息抽取 | 从文本和半结构化材料中抽取实体、mention、关系候选 |
| 实体识别 | 识别技能、工具、知识点、项目经历、偏好、约束等节点候选 |
| 实体消歧 / 实体链接 | 将不同词面、别名、候选实体对齐到标准节点 ID |
| 知识体系 / Schema / 本体 | 五层节点体系和四类边关系 |
| 知识融合 | 合并 seed 图谱、entityRepo、data_engine、DeepSeek 关系判断的产物 |
| 关系抽取 | 为节点对判断 `supports/requires/prefers/inhibits/none` |
| 知识表示 | 用节点和有向标签边表示职业推荐领域知识 |
| 知识推理 | 在 DAG 上传播用户证据，得到职业推荐、near miss、bridge、路径解释 |
