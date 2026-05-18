"""V5 五层平衡扩图 — 92 节点 + 149 边 + ~150 别名一次原子写入。

执行方式：
    python3 data_engine/scripts/v5_balanced_batch.py

依赖 data_engine.applier.apply_batch 的事务式写入 + 失败回滚。
新节点/边的具体内容来自 plan-mode 与用户对齐的"五层平衡"方案。
"""

from __future__ import annotations

from data_engine import applier
from data_engine.proposers.candidate import Candidate

# ---------------------------------------------------------------------------
# 节点定义：按层组织，每条 (id, label, *layer_specific_params)
# ---------------------------------------------------------------------------

# evidence 层：aggregator=source, cap=1.0
EVIDENCE_NODES: list[tuple[str, str]] = [
    # 编程语言 (10)
    ("javascript", "JavaScript"), ("typescript", "TypeScript"),
    ("go", "Go"), ("rust", "Rust"), ("scala", "Scala"),
    ("kotlin", "Kotlin"), ("swift", "Swift"), ("ruby", "Ruby"),
    ("php", "PHP"), ("csharp", "C#"),
    # 前端框架 (8)
    ("react", "React"), ("vue", "Vue.js"), ("angular", "Angular"),
    ("nextjs", "Next.js"), ("svelte", "Svelte"),
    ("tailwindcss", "Tailwind CSS"), ("webpack", "Webpack"),
    ("nodejs", "Node.js"),
    # 后端框架 (5)
    ("express", "Express.js"), ("spring", "Spring"),
    ("django", "Django"), ("flask", "Flask"), ("gin", "Gin"),
    # API 协议 (3)
    ("graphql", "GraphQL"), ("grpc", "gRPC"), ("openapi", "OpenAPI"),
    # 云 / 监控 (10)
    ("aws", "AWS"), ("gcp", "Google Cloud Platform"), ("azure", "Azure"),
    ("terraform", "Terraform"), ("ansible", "Ansible"),
    ("jenkins", "Jenkins"), ("github_actions", "GitHub Actions"),
    ("prometheus", "Prometheus"), ("grafana", "Grafana"), ("helm", "Helm"),
    # DevOps 工具 (3)
    ("istio", "Istio"), ("argocd", "Argo CD"), ("packer", "Packer"),
    # 数据库 (6)
    ("postgresql", "PostgreSQL"), ("mysql", "MySQL"),
    ("elasticsearch", "Elasticsearch"), ("cassandra", "Cassandra"),
    ("sqlite", "SQLite"), ("neo4j", "Neo4j"),
    # 数据工程 (6)
    ("spark", "Apache Spark"), ("kafka", "Apache Kafka"),
    ("airflow", "Apache Airflow"), ("snowflake", "Snowflake"),
    ("dbt", "dbt"), ("hadoop", "Hadoop"),
    # ML 库 (6)
    ("pandas", "pandas"), ("numpy", "NumPy"),
    ("scikit_learn", "scikit-learn"), ("mlflow", "MLflow"),
    ("xgboost", "XGBoost"), ("jupyter", "Jupyter"),
    # ML 概念 (4)
    ("cnn", "CNN"), ("rnn", "RNN"),
    ("transfer_learning", "迁移学习"), ("embedding", "Embedding"),
    # 移动 (4)
    ("ios", "iOS"), ("android", "Android"),
    ("react_native", "React Native"), ("flutter", "Flutter"),
    # 测试 (3)
    ("pytest", "pytest"), ("jest", "Jest"), ("selenium", "Selenium"),
    # 安全 (3)
    ("owasp", "OWASP"), ("oauth", "OAuth"), ("jwt", "JWT"),
    # LLM 周边 (3)
    ("vector_database", "向量数据库"), ("ollama", "Ollama"),
    ("chain_of_thought", "Chain of Thought"),
    # 系统 (1)
    ("microservices", "微服务"),
]

# ability 层：aggregator=weighted_sum_capped, cap=1.0
ABILITY_NODES: list[tuple[str, str, int]] = [
    # (id, label, min_support_count)
    ("cloud_native_practice", "云原生实践", 2),
    ("distributed_systems", "分布式系统知识", 1),
    ("system_design", "系统设计能力", 1),
    ("mobile_dev_practice", "移动开发实践", 1),
    ("security_practice", "安全实践", 1),
    ("testing_practice", "测试实践", 1),
    ("llm_practice", "LLM 应用实践", 1),
]

# composite 层：aggregator=soft_and, cap=1.0
COMPOSITE_NODES: list[tuple[str, str, int]] = [
    # (id, label, min_support_count)
    ("devops_engineering", "DevOps 工程能力", 3),
    ("mobile_engineering", "移动工程能力", 2),
    ("security_engineering", "安全工程能力", 2),
    ("llm_engineering", "LLM 工程能力", 2),
]

# direction 层：aggregator=penalty_gate, cap=1.0, penalty_floor=0.35
DIRECTION_NODES: list[tuple[str, str, float]] = [
    # (id, label, required_threshold)
    ("devops_direction", "DevOps 方向", 0.5),
    ("mobile_direction", "移动开发方向", 0.45),
    ("security_direction", "安全方向", 0.5),
    ("fullstack_direction", "全栈方向", 0.5),
    ("ai_engineering_direction", "AI 工程方向", 0.48),
]

# role 层：aggregator=hard_gate, cap=1.0
ROLE_NODES: list[tuple[str, str, float]] = [
    # (id, label, required_threshold)
    ("devops_engineer", "DevOps 工程师", 0.55),
    ("sre", "站点可靠性工程师 (SRE)", 0.55),
    ("mobile_engineer", "移动开发工程师", 0.5),
    ("security_engineer", "安全工程师", 0.55),
    ("fullstack_engineer", "全栈工程师", 0.55),
    ("ai_engineer", "AI 工程师", 0.52),
]

# ---------------------------------------------------------------------------
# 边定义
# ---------------------------------------------------------------------------

# 新 evidence → 现有/新上层 (~70 条 supports)
EVIDENCE_EDGES: list[tuple[str, str, float]] = [
    # 编程语言
    ("javascript", "web_fundamentals", 0.6),
    ("typescript", "web_fundamentals", 0.6),
    ("go", "programming_fundamentals", 0.55),
    ("rust", "programming_fundamentals", 0.55),
    ("scala", "programming_fundamentals", 0.5),
    ("kotlin", "programming_fundamentals", 0.5),
    ("swift", "programming_fundamentals", 0.5),
    ("ruby", "programming_fundamentals", 0.5),
    ("php", "programming_fundamentals", 0.5),
    ("csharp", "programming_fundamentals", 0.55),
    # 前端框架（evidence → composite 跨层 OK）
    ("react", "frontend_engineering", 0.65),
    ("vue", "frontend_engineering", 0.6),
    ("angular", "frontend_engineering", 0.55),
    ("nextjs", "frontend_engineering", 0.55),
    ("svelte", "frontend_engineering", 0.5),
    ("tailwindcss", "frontend_engineering", 0.45),
    ("webpack", "frontend_engineering", 0.45),
    ("nodejs", "backend_tech_stack", 0.55),
    # 后端框架
    ("express", "backend_tech_stack", 0.55),
    ("spring", "backend_tech_stack", 0.55),
    ("django", "backend_tech_stack", 0.55),
    ("flask", "backend_tech_stack", 0.55),
    ("gin", "backend_tech_stack", 0.5),
    # API 协议
    ("graphql", "backend_tech_stack", 0.5),
    ("grpc", "backend_tech_stack", 0.5),
    ("openapi", "backend_tech_stack", 0.45),
    # 云/监控 → 新 cloud_native_practice
    ("aws", "cloud_native_practice", 0.6),
    ("gcp", "cloud_native_practice", 0.55),
    ("azure", "cloud_native_practice", 0.55),
    ("terraform", "cloud_native_practice", 0.55),
    ("ansible", "cloud_native_practice", 0.5),
    ("jenkins", "cloud_native_practice", 0.5),
    ("github_actions", "cloud_native_practice", 0.5),
    ("prometheus", "cloud_native_practice", 0.5),
    ("grafana", "cloud_native_practice", 0.45),
    ("helm", "cloud_native_practice", 0.55),
    # DevOps tools → cloud_native_practice
    ("istio", "cloud_native_practice", 0.45),
    ("argocd", "cloud_native_practice", 0.45),
    ("packer", "cloud_native_practice", 0.4),
    # 数据库
    ("postgresql", "database_practice", 0.65),
    ("mysql", "database_practice", 0.65),
    ("elasticsearch", "database_practice", 0.5),
    ("cassandra", "database_practice", 0.5),
    ("sqlite", "database_practice", 0.5),
    ("neo4j", "database_practice", 0.45),
    # 数据工程
    ("spark", "data_tooling", 0.65),
    ("kafka", "data_tooling", 0.6),
    ("airflow", "data_tooling", 0.6),
    ("snowflake", "data_tooling", 0.55),
    ("dbt", "data_tooling", 0.55),
    ("hadoop", "data_tooling", 0.5),
    # ML libs
    ("pandas", "ml_basics", 0.6),
    ("numpy", "ml_basics", 0.55),
    ("scikit_learn", "ml_basics", 0.6),
    ("xgboost", "ml_basics", 0.5),
    ("jupyter", "ml_basics", 0.45),
    # ML lib 跨层到 composite
    ("mlflow", "ml_engineering", 0.55),
    # ML 概念
    ("cnn", "ml_basics", 0.5),
    ("rnn", "ml_basics", 0.5),
    ("transfer_learning", "ml_basics", 0.5),
    ("embedding", "ml_basics", 0.55),
    # 移动 → mobile_dev_practice (新)
    ("ios", "mobile_dev_practice", 0.65),
    ("android", "mobile_dev_practice", 0.65),
    ("react_native", "mobile_dev_practice", 0.55),
    ("flutter", "mobile_dev_practice", 0.55),
    # 跨界：swift/kotlin 也支持 mobile（除已挂 programming）
    # 测试 → testing_practice (新)
    ("pytest", "testing_practice", 0.55),
    ("jest", "testing_practice", 0.55),
    ("selenium", "testing_practice", 0.5),
    # 安全 → security_practice (新)
    ("owasp", "security_practice", 0.6),
    ("oauth", "security_practice", 0.55),
    ("jwt", "security_practice", 0.5),
    # LLM 周边 → llm_practice (新)
    ("vector_database", "llm_practice", 0.55),
    ("ollama", "llm_practice", 0.5),
    ("chain_of_thought", "llm_practice", 0.5),
    # 系统
    ("microservices", "distributed_systems", 0.6),
    ("microservices", "system_design", 0.5),
]

# 现有 evidence 节点 → 新 ability（让新 ability 由现有原子节点驱动）
CROSS_EVIDENCE_TO_NEW_ABILITY: list[tuple[str, str, float]] = [
    # cloud_native_practice 由 docker/kubernetes 已 supports backend_tech_stack；这里直挂
    ("kubernetes", "cloud_native_practice", 0.65),
    ("docker", "cloud_native_practice", 0.55),
    # distributed_systems
    ("redis", "distributed_systems", 0.5),
    # mobile_dev_practice
    ("swift", "mobile_dev_practice", 0.5),
    ("kotlin", "mobile_dev_practice", 0.5),
    # llm_practice 用现有 LLM evidence
    ("prompt_engineering", "llm_practice", 0.6),
    ("rag", "llm_practice", 0.6),
    ("fine_tuning", "llm_practice", 0.55),
    ("langchain", "llm_practice", 0.55),
]

# ability → composite (evidence→composite 跨层、ability→composite 跨层都允许)
ABILITY_TO_COMPOSITE_EDGES: list[tuple[str, str, str, float]] = [
    # (source, target, relation, weight)
    ("cloud_native_practice", "devops_engineering", "supports", 0.6),
    ("distributed_systems", "devops_engineering", "supports", 0.5),
    ("linux", "devops_engineering", "supports", 0.5),
    ("programming_fundamentals", "devops_engineering", "supports", 0.4),

    ("mobile_dev_practice", "mobile_engineering", "supports", 0.7),
    ("programming_fundamentals", "mobile_engineering", "supports", 0.4),

    ("security_practice", "security_engineering", "supports", 0.7),
    ("programming_fundamentals", "security_engineering", "supports", 0.4),

    ("llm_practice", "llm_engineering", "supports", 0.7),
    ("ml_basics", "llm_engineering", "supports", 0.5),
]

# composite → direction
COMPOSITE_TO_DIRECTION_EDGES: list[tuple[str, str, str, float]] = [
    ("devops_engineering", "devops_direction", "supports", 0.7),
    ("cloud_native_practice", "devops_direction", "supports", 0.6),
    ("distributed_systems", "devops_direction", "supports", 0.5),

    ("mobile_engineering", "mobile_direction", "supports", 0.7),
    ("mobile_dev_practice", "mobile_direction", "supports", 0.6),

    ("security_engineering", "security_direction", "supports", 0.7),
    ("security_practice", "security_direction", "supports", 0.6),

    ("backend_engineering", "fullstack_direction", "supports", 0.5),
    ("frontend_engineering", "fullstack_direction", "supports", 0.5),

    ("llm_engineering", "ai_engineering_direction", "supports", 0.7),
    ("llm_practice", "ai_engineering_direction", "supports", 0.6),
    ("ml_engineering", "ai_engineering_direction", "supports", 0.4),
]

# direction/composite/ability → role
ROLE_INBOUND_EDGES: list[tuple[str, str, str, float]] = [
    # devops_engineer
    ("devops_engineering", "devops_engineer", "requires", 0.92),
    ("devops_direction", "devops_engineer", "requires", 0.95),
    ("cloud_native_practice", "devops_engineer", "requires", 0.7),
    # sre
    ("devops_engineering", "sre", "requires", 0.85),
    ("distributed_systems", "sre", "requires", 0.7),
    ("system_design", "sre", "requires", 0.6),
    ("devops_direction", "sre", "supports", 0.5),
    # mobile_engineer
    ("mobile_engineering", "mobile_engineer", "requires", 0.92),
    ("mobile_direction", "mobile_engineer", "requires", 0.95),
    ("mobile_dev_practice", "mobile_engineer", "requires", 0.7),
    # security_engineer
    ("security_engineering", "security_engineer", "requires", 0.92),
    ("security_direction", "security_engineer", "requires", 0.95),
    ("security_practice", "security_engineer", "requires", 0.7),
    # fullstack_engineer
    ("backend_engineering", "fullstack_engineer", "requires", 0.65),
    ("frontend_engineering", "fullstack_engineer", "requires", 0.65),
    ("fullstack_direction", "fullstack_engineer", "requires", 0.95),
    # ai_engineer
    ("llm_engineering", "ai_engineer", "requires", 0.92),
    ("ai_engineering_direction", "ai_engineer", "requires", 0.95),
    ("llm_practice", "ai_engineer", "requires", 0.7),
    ("ml_basics", "ai_engineer", "supports", 0.5),
]

# ---------------------------------------------------------------------------
# 别名（中英双语，每个新节点 1-3 条）
# ---------------------------------------------------------------------------

ALIASES: dict[str, list[str]] = {
    # 编程语言
    "javascript": ["javascript", "js"],
    "typescript": ["typescript", "ts"],
    "go": ["go", "golang"],
    "rust": ["rust"],
    "scala": ["scala"],
    "kotlin": ["kotlin"],
    "swift": ["swift"],
    "ruby": ["ruby", "ruby on rails", "rails"],
    "php": ["php"],
    "csharp": ["c#", "csharp", ".net"],
    # 前端
    "react": ["react", "reactjs", "react.js"],
    "vue": ["vue", "vuejs", "vue.js"],
    "angular": ["angular", "angularjs"],
    "nextjs": ["next.js", "nextjs", "next"],
    "svelte": ["svelte", "sveltejs", "sveltekit"],
    "tailwindcss": ["tailwind", "tailwindcss", "tailwind css"],
    "webpack": ["webpack"],
    "nodejs": ["node.js", "nodejs", "node"],
    # 后端
    "express": ["express", "expressjs", "express.js"],
    "spring": ["spring", "spring boot", "springboot"],
    "django": ["django"],
    "flask": ["flask"],
    "gin": ["gin"],
    # API
    "graphql": ["graphql", "gql"],
    "grpc": ["grpc"],
    "openapi": ["openapi", "swagger"],
    # 云
    "aws": ["aws", "amazon web services"],
    "gcp": ["gcp", "google cloud", "google cloud platform"],
    "azure": ["azure", "microsoft azure"],
    "terraform": ["terraform", "iac"],
    "ansible": ["ansible"],
    "jenkins": ["jenkins"],
    "github_actions": ["github actions", "gh actions"],
    "prometheus": ["prometheus"],
    "grafana": ["grafana"],
    "helm": ["helm", "helm chart"],
    "istio": ["istio", "service mesh"],
    "argocd": ["argo cd", "argocd"],
    "packer": ["packer"],
    # 数据库
    "postgresql": ["postgresql", "postgres", "pgsql"],
    "mysql": ["mysql"],
    "elasticsearch": ["elasticsearch", "elastic", "es"],
    "cassandra": ["cassandra"],
    "sqlite": ["sqlite"],
    "neo4j": ["neo4j", "图数据库"],
    # 数据工程
    "spark": ["spark", "apache spark", "pyspark"],
    "kafka": ["kafka", "apache kafka"],
    "airflow": ["airflow", "apache airflow"],
    "snowflake": ["snowflake"],
    "dbt": ["dbt", "data build tool"],
    "hadoop": ["hadoop", "hdfs"],
    # ML libs
    "pandas": ["pandas"],
    "numpy": ["numpy"],
    "scikit_learn": ["scikit-learn", "sklearn"],
    "mlflow": ["mlflow"],
    "xgboost": ["xgboost"],
    "jupyter": ["jupyter", "jupyter notebook"],
    # ML 概念
    "cnn": ["cnn", "卷积神经网络", "convolutional neural network"],
    "rnn": ["rnn", "循环神经网络"],
    "transfer_learning": ["迁移学习", "transfer learning"],
    "embedding": ["embedding", "向量表示", "词嵌入"],
    # 移动
    "ios": ["ios", "苹果"],
    "android": ["android", "安卓"],
    "react_native": ["react native", "rn"],
    "flutter": ["flutter"],
    # 测试
    "pytest": ["pytest"],
    "jest": ["jest"],
    "selenium": ["selenium"],
    # 安全
    "owasp": ["owasp"],
    "oauth": ["oauth", "oauth2"],
    "jwt": ["jwt", "json web token"],
    # LLM
    "vector_database": ["向量数据库", "vector database", "vector db"],
    "ollama": ["ollama"],
    "chain_of_thought": ["chain of thought", "cot", "思维链"],
    # 系统
    "microservices": ["microservices", "微服务"],

    # 新 ability
    "cloud_native_practice": ["云原生", "cloud native", "云原生实践"],
    "distributed_systems": ["分布式系统", "distributed systems"],
    "system_design": ["系统设计", "system design"],
    "mobile_dev_practice": ["移动开发", "mobile dev", "mobile development"],
    "security_practice": ["安全实践", "security practice"],
    "testing_practice": ["测试实践", "testing", "qa"],
    "llm_practice": ["llm 应用", "llm practice", "llm 工程"],

    # 新 composite
    "devops_engineering": ["devops 工程", "devops engineering"],
    "mobile_engineering": ["移动工程", "mobile engineering"],
    "security_engineering": ["安全工程", "security engineering"],
    "llm_engineering": ["llm 工程", "llm engineering", "大模型工程"],

    # 新 direction
    "devops_direction": ["devops 方向", "devops 路线"],
    "mobile_direction": ["移动方向", "移动开发方向"],
    "security_direction": ["安全方向"],
    "fullstack_direction": ["全栈方向"],
    "ai_engineering_direction": ["ai 工程方向", "ai engineering"],

    # 新 role
    "devops_engineer": ["devops 工程师", "devops engineer"],
    "sre": ["sre", "站点可靠性工程师", "site reliability engineer"],
    "mobile_engineer": ["移动开发工程师", "mobile engineer", "app 工程师"],
    "security_engineer": ["安全工程师", "security engineer"],
    "fullstack_engineer": ["全栈工程师", "full-stack engineer", "fullstack"],
    "ai_engineer": ["ai 工程师", "ai engineer", "llm 工程师"],
}


# ---------------------------------------------------------------------------
# 构造 Candidate 列表
# ---------------------------------------------------------------------------

def build_node_candidates() -> list[Candidate]:
    candidates: list[Candidate] = []

    for nid, label in EVIDENCE_NODES:
        candidates.append(Candidate(
            kind="node",
            payload={"id": nid, "label": label, "layer": "evidence",
                     "aggregator": "source", "cap": 1.0},
            confidence=1.0, auto_apply_eligible=True,
            source_proposer="curated-v5",
        ))

    for nid, label, mins in ABILITY_NODES:
        candidates.append(Candidate(
            kind="node",
            payload={"id": nid, "label": label, "layer": "ability",
                     "aggregator": "weighted_sum_capped", "cap": 1.0,
                     "min_support_count": mins},
            confidence=1.0, auto_apply_eligible=True,
            source_proposer="curated-v5",
        ))

    for nid, label, mins in COMPOSITE_NODES:
        candidates.append(Candidate(
            kind="node",
            payload={"id": nid, "label": label, "layer": "composite",
                     "aggregator": "soft_and", "cap": 1.0,
                     "min_support_count": mins},
            confidence=1.0, auto_apply_eligible=True,
            source_proposer="curated-v5",
        ))

    for nid, label, thresh in DIRECTION_NODES:
        candidates.append(Candidate(
            kind="node",
            payload={"id": nid, "label": label, "layer": "direction",
                     "aggregator": "penalty_gate", "cap": 1.0,
                     "required_threshold": thresh, "penalty_floor": 0.35},
            confidence=1.0, auto_apply_eligible=True,
            source_proposer="curated-v5",
        ))

    for nid, label, thresh in ROLE_NODES:
        candidates.append(Candidate(
            kind="node",
            payload={"id": nid, "label": label, "layer": "role",
                     "aggregator": "hard_gate", "cap": 1.0,
                     "required_threshold": thresh},
            confidence=1.0, auto_apply_eligible=True,
            source_proposer="curated-v5",
        ))

    return candidates


def build_edge_candidates() -> list[Candidate]:
    out: list[Candidate] = []

    def _add(src: str, tgt: str, rel: str, weight: float) -> None:
        out.append(Candidate(
            kind="edge",
            payload={"source": src, "target": tgt, "relation": rel, "weight": weight},
            confidence=1.0, auto_apply_eligible=True,
            source_proposer="curated-v5",
        ))

    for src, tgt, w in EVIDENCE_EDGES:
        _add(src, tgt, "supports", w)
    for src, tgt, w in CROSS_EVIDENCE_TO_NEW_ABILITY:
        _add(src, tgt, "supports", w)
    for src, tgt, rel, w in ABILITY_TO_COMPOSITE_EDGES:
        _add(src, tgt, rel, w)
    for src, tgt, rel, w in COMPOSITE_TO_DIRECTION_EDGES:
        _add(src, tgt, rel, w)
    for src, tgt, rel, w in ROLE_INBOUND_EDGES:
        _add(src, tgt, rel, w)
    return out


def build_alias_candidates() -> list[Candidate]:
    out: list[Candidate] = []
    for entity, names in ALIASES.items():
        for name in names:
            out.append(Candidate(
                kind="alias",
                payload={"entity_id": entity, "alias": name},
                confidence=1.0, auto_apply_eligible=True,
                source_proposer="curated-v5",
            ))
    return out


def main() -> None:
    nodes = build_node_candidates()
    edges = build_edge_candidates()
    aliases = build_alias_candidates()
    print(f"prepared: {len(nodes)} nodes, {len(edges)} edges, {len(aliases)} aliases")
    report = applier.apply_batch(nodes, edges, aliases)
    print(report.to_dict())


if __name__ == "__main__":
    main()
