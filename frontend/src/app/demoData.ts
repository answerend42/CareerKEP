import type {
  BridgeCard,
  DemoState,
  EvidenceItem,
  RecommendationCard,
  RecommendationResponse,
  RoleOption,
  DiagnosticSnapshot,
  RobustnessCaseResult,
  RobustnessReport,
  StageEdge,
  StageNode,
  ScenarioPreset,
  TargetRoleAnalysis
} from './types';

interface RoleProfile {
  nodeId: string;
  label: string;
  direction: string;
  required: string[];
  preferred: string[];
  blockers: string[];
  path: string[];
}

interface PropagationSnapshot {
  layers: {
    layer: StageNode['layer'];
    label: string;
    nodes: StageNode[];
  }[];
  edges: StageEdge[];
}

interface NodeDefinition {
  id: string;
  label: string;
  layer: StageNode['layer'];
  aliases: string[];
  scoreHint: number;
  polarity?: 'positive' | 'negative';
}

interface SignalTrace {
  clauses: string[];
  matchedSignals: string[];
  negatedSignals: string[];
}

interface TextAnalysis {
  evidenceMap: Map<string, number>;
  signalTrace: SignalTrace;
}

const clamp01 = (value: number): number => Math.max(0, Math.min(1, value));

const nodeCatalog: NodeDefinition[] = [
  { id: 'python', label: 'Python', layer: 'evidence', aliases: ['python', 'py'], scoreHint: 0.95 },
  { id: 'sql', label: 'SQL', layer: 'evidence', aliases: ['sql', '数据库'], scoreHint: 0.92 },
  { id: 'frontend_project', label: '前端项目', layer: 'evidence', aliases: ['前端项目', 'web项目'], scoreHint: 0.9 },
  { id: 'communication', label: '沟通表达', layer: 'evidence', aliases: ['沟通', '表达'], scoreHint: 0.88 },
  { id: 'cpp_gap', label: '不擅长 C++', layer: 'evidence', aliases: ['c++', 'cpp', '不擅长 c++', '不会 c++'], scoreHint: 0.82, polarity: 'negative' },
  { id: 'math', label: '数学基础', layer: 'evidence', aliases: ['数学', '线代'], scoreHint: 0.82 },
  { id: 'data_viz', label: '数据分析', layer: 'evidence', aliases: ['数据分析', '分析'], scoreHint: 0.8 },
  { id: 'cloud', label: '云平台', layer: 'evidence', aliases: ['云', '云平台', 'docker'], scoreHint: 0.78 },
  { id: 'programming', label: '编程基础', layer: 'ability', aliases: ['编程基础'], scoreHint: 0.5 },
  { id: 'database', label: '数据库实践', layer: 'ability', aliases: ['数据库实践'], scoreHint: 0.5 },
  { id: 'frontend_dev', label: 'Web 开发能力', layer: 'composite', aliases: ['web开发', '前端能力'], scoreHint: 0.5 },
  { id: 'backend_engineering', label: '后端工程能力', layer: 'composite', aliases: ['后端工程'], scoreHint: 0.5 },
  { id: 'data_engineering', label: '数据工程能力', layer: 'composite', aliases: ['数据工程'], scoreHint: 0.5 },
  { id: 'ml_engineering', label: '机器学习工程能力', layer: 'composite', aliases: ['机器学习工程'], scoreHint: 0.5 },
  { id: 'data_analysis', label: '数据分析能力', layer: 'composite', aliases: ['数据分析能力'], scoreHint: 0.5 },
  { id: 'communication_skill', label: '协作沟通', layer: 'ability', aliases: ['协作沟通'], scoreHint: 0.5 },
  { id: 'direction_backend', label: '后端方向', layer: 'direction', aliases: ['后端方向'], scoreHint: 0.5 },
  { id: 'direction_frontend', label: '前端方向', layer: 'direction', aliases: ['前端方向'], scoreHint: 0.5 },
  { id: 'direction_data', label: '数据方向', layer: 'direction', aliases: ['数据方向'], scoreHint: 0.5 },
  { id: 'direction_ml', label: '机器学习方向', layer: 'direction', aliases: ['机器学习方向'], scoreHint: 0.5 },
  { id: 'backend_role', label: '后端开发工程师', layer: 'role', aliases: ['后端开发工程师', '后端'], scoreHint: 0.5 },
  { id: 'frontend_role', label: '前端开发工程师', layer: 'role', aliases: ['前端开发工程师', '前端'], scoreHint: 0.5 },
  { id: 'data_role', label: '数据工程师', layer: 'role', aliases: ['数据工程师'], scoreHint: 0.5 },
  { id: 'ml_role', label: '机器学习工程师', layer: 'role', aliases: ['机器学习工程师'], scoreHint: 0.5 },
  { id: 'pm_role', label: '技术产品经理', layer: 'role', aliases: ['技术产品经理'], scoreHint: 0.5 }
];

const NEGATION_WORDS = [
  '不',
  '没',
  '无',
  '否',
  '不会',
  '不擅长',
  '不熟悉',
  '不太',
  '缺少',
  '欠缺',
  '拒绝',
  '避免',
  'not',
  'no',
  'never',
  'without',
  "don't",
  'do not'
];

const normalizeToken = (value: string): string => value.normalize('NFKC').trim().toLowerCase();

const extractClauses = (text: string): string[] =>
  text
    .normalize('NFKC')
    .split(/[\n\r。！？!?；;，,、|/\\]+/)
    .map((part) => part.trim())
    .filter(Boolean);

const analyzeInputText = (text: string, evidence: EvidenceItem[]): TextAnalysis => {
  const evidenceMap = new Map<string, number>();

  for (const item of evidence) {
    evidenceMap.set(item.nodeId, clamp01(item.score));
  }

  const clauses = extractClauses(text);
  const matchedSignals = new Set<string>();
  const negatedSignals = new Set<string>();

  for (const clause of clauses) {
    const clauseToken = normalizeToken(clause);

    for (const item of nodeCatalog) {
      for (const alias of item.aliases) {
        const aliasToken = normalizeToken(alias);
        if (!aliasToken || !clauseToken.includes(aliasToken)) {
          continue;
        }

        const aliasIndex = clauseToken.indexOf(aliasToken);
        const prefix = clauseToken.slice(Math.max(0, aliasIndex - 8), aliasIndex);
        const negated = NEGATION_WORDS.some((word) => prefix.includes(word));

        if (item.polarity === 'negative') {
          negatedSignals.add(item.label);
        } else if (!negated) {
          matchedSignals.add(item.label);
        }

        if (item.polarity === 'negative') {
          const current = evidenceMap.get(item.id) ?? 0;
          const nextScore = negated ? item.scoreHint : item.scoreHint * 0.85;
          evidenceMap.set(item.id, clamp01(Math.max(current, nextScore)));
        } else if (!negated) {
          const current = evidenceMap.get(item.id) ?? 0;
          evidenceMap.set(item.id, clamp01(Math.max(current, item.scoreHint)));
        }

        if (item.id === 'frontend_project') {
          const programmingScore = clamp01(item.scoreHint * 0.72);
          const existingProgramming = evidenceMap.get('programming') ?? 0;
          // 前端项目通常也能间接说明一定的编程基础，所以这里给一个温和的桥接增益。
          evidenceMap.set('programming', clamp01(Math.max(existingProgramming, programmingScore)));
        }
      }
    }
  }

  return {
    evidenceMap,
    signalTrace: {
      clauses,
      matchedSignals: [...matchedSignals],
      negatedSignals: [...negatedSignals]
    }
  };
};

const roleOptions: RoleOption[] = nodeCatalog
  .filter((item) => item.layer === 'role')
  .map((item) => ({
    nodeId: item.id,
    label: item.label,
    searchTerms: item.aliases
  }));

const roleProfiles: RoleProfile[] = [
  {
    nodeId: 'backend_role',
    label: '后端开发工程师',
    direction: 'direction_backend',
    required: ['python', 'sql', 'programming'],
    preferred: ['cloud', 'communication'],
    blockers: ['cpp_gap'],
    path: ['Python -> 编程基础', 'SQL -> 数据库实践', '编程基础 -> 后端方向', '后端方向 -> 后端开发工程师']
  },
  {
    nodeId: 'frontend_role',
    label: '前端开发工程师',
    direction: 'direction_frontend',
    required: ['frontend_project', 'programming'],
    preferred: ['communication', 'cloud'],
    blockers: [],
    path: ['前端项目 -> Web 开发能力', 'Web 开发能力 -> 前端方向', '前端方向 -> 前端开发工程师']
  },
  {
    nodeId: 'data_role',
    label: '数据工程师',
    direction: 'direction_data',
    required: ['sql', 'cloud', 'data_viz'],
    preferred: ['programming', 'communication'],
    blockers: [],
    path: ['SQL -> 数据库实践', '数据分析 -> 数据分析能力', '云平台 -> 数据工程能力', '数据方向 -> 数据工程师']
  },
  {
    nodeId: 'ml_role',
    label: '机器学习工程师',
    direction: 'direction_ml',
    required: ['math', 'python'],
    preferred: ['programming', 'data_viz'],
    blockers: ['cpp_gap'],
    path: ['数学基础 -> 算法基础', 'Python -> 编程基础', '机器学习方向 -> 机器学习工程师']
  },
  {
    nodeId: 'pm_role',
    label: '技术产品经理',
    direction: 'direction_frontend',
    required: ['communication', 'frontend_project'],
    preferred: ['cloud', 'data_viz'],
    blockers: [],
    path: ['沟通表达 -> 协作沟通', '前端项目 -> Web 开发能力', '协作沟通 -> 技术产品经理']
  }
];

const evidenceTemplates: EvidenceItem[] = [
  { nodeId: 'python', label: 'Python', score: 0.9, source: '用户输入', rawText: '会 Python，做过数据处理脚本' },
  { nodeId: 'sql', label: 'SQL', score: 0.88, source: '用户输入', rawText: '熟悉 SQL 和基础查询优化' },
  { nodeId: 'frontend_project', label: '前端项目', score: 0.82, source: '用户输入', rawText: '做过前端项目和页面联调' },
  { nodeId: 'communication', label: '沟通表达', score: 0.8, source: '用户输入', rawText: '也比较擅长沟通协作' },
  { nodeId: 'cpp_gap', label: '不擅长 C++', score: 0.7, source: '用户输入', rawText: '不太擅长 C++' }
];

const scoreProfile = (
  profile: RoleProfile,
  evidenceMap: Map<string, number>,
  tuning: DemoState['tuning']
): RecommendationCard => {
  const hitEntries: Array<[string, number]> = [];
  let supportScore = 0;
  let preferredScore = 0;
  let blockerPenalty = 0;

  for (const requirement of profile.required) {
    const value = evidenceMap.get(requirement) ?? 0;
    if (value > 0) {
      hitEntries.push([requirement, value]);
    }
    supportScore += value * 0.28;
  }

  for (const preferred of profile.preferred) {
    const value = evidenceMap.get(preferred) ?? 0;
    preferredScore += value * 0.17;
  }

  for (const blocker of profile.blockers) {
    const value = evidenceMap.get(blocker) ?? 0;
    blockerPenalty += value * 0.26;
  }

  const directionBoost = evidenceMap.get(profile.direction) ?? 0;
  // 负向容忍度越高，对 blocker 的惩罚越弱，适合演示“放宽筛选”的效果。
  const penaltyRelief = 1 - clamp01(tuning.penaltyTolerance * 0.85);
  const tuningBoost = tuning.confidence * 0.06 + tuning.exploration * 0.04;
  const score = clamp01(supportScore + preferredScore + directionBoost * 0.25 + tuningBoost - blockerPenalty * penaltyRelief);
  const missing = profile.required
    .filter((item) => !(evidenceMap.get(item) ?? 0))
    .map((item) => nodeCatalog.find((node) => node.id === item)?.label ?? item);

  return {
    nodeId: profile.nodeId,
    label: profile.label,
    score,
    reason: hitEntries.length
      ? hitEntries.map(([item, value]) => `${nodeCatalog.find((node) => node.id === item)?.label ?? item} 命中 ${value.toFixed(2)}`)
      : ['暂无直接证据命中'],
    missing,
    path: profile.path
  };
};

const buildPropagationSnapshot = (evidenceMap: Map<string, number>, tuning: DemoState['tuning']): PropagationSnapshot => {
  const evidenceLayer: StageNode[] = nodeCatalog
    .filter((item) => item.layer === 'evidence')
    .map((item) => ({
      id: item.id,
      label: item.label,
      layer: item.layer,
      score: evidenceMap.get(item.id) ?? 0,
      detail: `根证据 · ${item.aliases[0]}`
    }));

  const abilityLayer: StageNode[] = [
    {
      id: 'programming',
      label: '编程基础',
      layer: 'ability',
      score:
        clamp01((evidenceMap.get('python') ?? 0) * 0.9 + (evidenceMap.get('frontend_project') ?? 0) * 0.2 + tuning.confidence * 0.05),
      detail: 'Python 与项目实践共同抬升'
    },
    {
      id: 'database',
      label: '数据库实践',
      layer: 'ability',
      score: clamp01((evidenceMap.get('sql') ?? 0) * 0.95 + (evidenceMap.get('data_viz') ?? 0) * 0.15),
      detail: 'SQL 是主要输入'
    },
    {
      id: 'communication_skill',
      label: '协作沟通',
      layer: 'ability',
      score: clamp01((evidenceMap.get('communication') ?? 0) * 0.96 + tuning.exploration * 0.08),
      detail: '沟通输入直接触发'
    }
  ];

  const compositeLayer: StageNode[] = [
    {
      id: 'backend_engineering',
      label: '后端工程能力',
      layer: 'composite',
      score: clamp01(abilityLayer[0].score * 0.62 + abilityLayer[1].score * 0.55 + (evidenceMap.get('cloud') ?? 0) * 0.2),
      detail: '编程与数据库共同支持'
    },
    {
      id: 'frontend_dev',
      label: 'Web 开发能力',
      layer: 'composite',
      score: clamp01((evidenceMap.get('frontend_project') ?? 0) * 0.88 + abilityLayer[2].score * 0.14),
      detail: '前端项目是最强信号'
    },
    {
      id: 'data_engineering',
      label: '数据工程能力',
      layer: 'composite',
      score: clamp01(abilityLayer[1].score * 0.6 + (evidenceMap.get('cloud') ?? 0) * 0.3),
      detail: '数据库和云平台共同支撑'
    },
    {
      id: 'ml_engineering',
      label: '机器学习工程能力',
      layer: 'composite',
      score: clamp01((evidenceMap.get('math') ?? 0) * 0.65 + (evidenceMap.get('python') ?? 0) * 0.42),
      detail: '数学与 Python 共同促进'
    },
    {
      id: 'data_analysis',
      label: '数据分析能力',
      layer: 'composite',
      score: clamp01((evidenceMap.get('data_viz') ?? 0) * 0.9 + abilityLayer[1].score * 0.18),
      detail: '数据分析输入占主导'
    }
  ];

  const directionLayer: StageNode[] = [
    {
      id: 'direction_backend',
      label: '后端方向',
      layer: 'direction',
      score: clamp01(compositeLayer[0].score * 0.74 + compositeLayer[2].score * 0.2),
      detail: '偏工程化的后端职业通道'
    },
    {
      id: 'direction_frontend',
      label: '前端方向',
      layer: 'direction',
      score: clamp01(compositeLayer[1].score * 0.88 + abilityLayer[2].score * 0.12),
      detail: '前端项目让方向得分更直接'
    },
    {
      id: 'direction_data',
      label: '数据方向',
      layer: 'direction',
      score: clamp01(compositeLayer[2].score * 0.72 + compositeLayer[4].score * 0.24),
      detail: '数据库与数据分析双支撑'
    },
    {
      id: 'direction_ml',
      label: '机器学习方向',
      layer: 'direction',
      score: clamp01(compositeLayer[3].score * 0.82),
      detail: '数学基础决定上限'
    }
  ];

  const roleLayer: StageNode[] = roleProfiles.map((profile) => {
    const directionScore = directionLayer.find((item) => item.id === profile.direction)?.score ?? 0;
    const directSupport = profile.required.reduce((sum, item) => sum + (evidenceMap.get(item) ?? 0) * 0.22, 0);
    const penalty = profile.blockers.reduce((sum, item) => sum + (evidenceMap.get(item) ?? 0) * 0.18, 0);
    const penaltyRelief = 1 - clamp01(tuning.penaltyTolerance * 0.7);
    return {
      id: profile.nodeId,
      label: profile.label,
      layer: 'role',
      score: clamp01(directionScore * 0.58 + directSupport - penalty * penaltyRelief + tuning.confidence * 0.05),
      detail: profile.path[profile.path.length - 1] ?? '岗位节点'
    };
  });

  const edges: StageEdge[] = [
    { source: 'python', target: 'programming', relation: 'supports', contribution: clamp01((evidenceMap.get('python') ?? 0) * 0.9) },
    { source: 'sql', target: 'database', relation: 'supports', contribution: clamp01((evidenceMap.get('sql') ?? 0) * 0.95) },
    { source: 'frontend_project', target: 'frontend_dev', relation: 'evidences', contribution: clamp01((evidenceMap.get('frontend_project') ?? 0) * 0.88) },
    { source: 'communication', target: 'communication_skill', relation: 'supports', contribution: clamp01((evidenceMap.get('communication') ?? 0) * 0.96) },
    { source: 'cloud', target: 'backend_engineering', relation: 'supports', contribution: clamp01((evidenceMap.get('cloud') ?? 0) * 0.7) },
    { source: 'cloud', target: 'data_engineering', relation: 'supports', contribution: clamp01((evidenceMap.get('cloud') ?? 0) * 0.6) }
  ];

  return {
    layers: [
      { layer: 'evidence', label: '输入证据', nodes: evidenceLayer },
      { layer: 'ability', label: '基础能力', nodes: abilityLayer },
      { layer: 'composite', label: '复合能力', nodes: compositeLayer },
      { layer: 'direction', label: '岗位方向', nodes: directionLayer },
      { layer: 'role', label: '职业节点', nodes: roleLayer }
    ],
    edges
  };
};

const buildBridgeRecommendations = (evidenceMap: Map<string, number>): BridgeCard[] => {
  const bridgePool: BridgeCard[] = [
    { nodeId: 'backend_engineering', label: '后端工程能力', score: clamp01((evidenceMap.get('python') ?? 0) * 0.55 + (evidenceMap.get('sql') ?? 0) * 0.45), why: 'Python 与 SQL 共同构成后端桥接能力' },
    { nodeId: 'frontend_dev', label: 'Web 开发能力', score: clamp01((evidenceMap.get('frontend_project') ?? 0) * 0.72), why: '前端项目足以把你桥接到前端方向' },
    { nodeId: 'data_engineering', label: '数据工程能力', score: clamp01((evidenceMap.get('sql') ?? 0) * 0.6 + (evidenceMap.get('cloud') ?? 0) * 0.3), why: '数据库和云平台适合做数据方向过渡' }
  ];

  return bridgePool.sort((left, right) => right.score - left.score).slice(0, 3);
};

const buildTargetAnalysis = (targetRole: string, evidenceMap: Map<string, number>): TargetRoleAnalysis => {
  const profile = roleProfiles.find((item) => item.label === targetRole || item.nodeId === targetRole) ?? roleProfiles[0];
  const matchedRequired = profile.required.filter((item) => (evidenceMap.get(item) ?? 0) > 0);
  const missing = profile.required.filter((item) => (evidenceMap.get(item) ?? 0) <= 0);

  return {
    nodeId: profile.nodeId,
    label: profile.label,
    coverage: clamp01(matchedRequired.length / profile.required.length),
    strengths: matchedRequired.map((item) => nodeCatalog.find((node) => node.id === item)?.label ?? item),
    gaps: missing.map((item) => nodeCatalog.find((node) => node.id === item)?.label ?? item),
    path: profile.path
  };
};

export const defaultDemoState: DemoState = {
  text: '我会 Python、SQL，做过前端项目，也比较擅长沟通；希望看看适合哪些计算机相关职业。',
  targetRole: '后端开发工程师',
  topK: 5,
  evidence: evidenceTemplates,
  tuning: {
    confidence: 0.72,
    exploration: 0.58,
    penaltyTolerance: 0.42
  }
};

export const roleCatalog = roleOptions;

export const scenarioPresets: ScenarioPreset[] = [
  {
    id: 'backend',
    label: '后端转向',
    description: '偏工程化、数据库和云平台信号更强',
    kind: 'normal',
    state: {
      text: '我会 Python 和 SQL，做过接口联调，也接触过云平台部署。',
      targetRole: '后端开发工程师',
      topK: 5,
      evidence: [
        { nodeId: 'python', label: 'Python', score: 0.94, source: '预设', rawText: 'Python' },
        { nodeId: 'sql', label: 'SQL', score: 0.9, source: '预设', rawText: 'SQL' },
        { nodeId: 'cloud', label: '云平台', score: 0.76, source: '预设', rawText: '云平台' }
      ],
      tuning: {
        confidence: 0.76,
        exploration: 0.44,
        penaltyTolerance: 0.38
      }
    }
  },
  {
    id: 'frontend',
    label: '前端优先',
    description: '前端项目和协作表达更明显',
    kind: 'normal',
    state: {
      text: '我做过前端项目，喜欢和产品、设计协作，愿意继续做 Web 开发。',
      targetRole: '前端开发工程师',
      topK: 5,
      evidence: [
        { nodeId: 'frontend_project', label: '前端项目', score: 0.94, source: '预设', rawText: '前端项目' },
        { nodeId: 'communication', label: '沟通表达', score: 0.82, source: '预设', rawText: '沟通表达' }
      ],
      tuning: {
        confidence: 0.68,
        exploration: 0.72,
        penaltyTolerance: 0.46
      }
    }
  },
  {
    id: 'data',
    label: '数据方向',
    description: 'SQL、数据分析和数学基础更突出',
    kind: 'normal',
    state: {
      text: '我更熟悉 SQL、数据分析和一些数学基础，想看数据工程或机器学习方向。',
      targetRole: '数据工程师',
      topK: 5,
      evidence: [
        { nodeId: 'sql', label: 'SQL', score: 0.95, source: '预设', rawText: 'SQL' },
        { nodeId: 'data_viz', label: '数据分析', score: 0.86, source: '预设', rawText: '数据分析' },
        { nodeId: 'math', label: '数学基础', score: 0.72, source: '预设', rawText: '数学基础' }
      ],
      tuning: {
        confidence: 0.64,
        exploration: 0.65,
        penaltyTolerance: 0.4
      }
    }
  },
  {
    id: 'noise',
    label: '噪声输入',
    description: '长文本、重复词和无关语句混在一起',
    kind: 'stress',
    state: {
      text:
        '日志、报错、日报、会议纪要都塞进来，但是我还是会 Python、SQL、Python、SQL，还做过前端项目。' +
        '其他内容全部是噪声：abc123、###、!!!、临时文档、重复重复重复。',
      targetRole: '后端开发工程师',
      topK: 5,
      evidence: [
        { nodeId: 'python', label: 'Python', score: 0.86, source: '压力测试', rawText: 'Python' },
        { nodeId: 'sql', label: 'SQL', score: 0.84, source: '压力测试', rawText: 'SQL' }
      ],
      tuning: {
        confidence: 0.7,
        exploration: 0.52,
        penaltyTolerance: 0.36
      }
    }
  },
  {
    id: 'conflict',
    label: '冲突输入',
    description: '同一段话同时包含正向和否定信号',
    kind: 'stress',
    state: {
      text: '我会 Python 和 SQL，但不想做后端，也不太擅长 C++，更想试试前端或产品协作。',
      targetRole: '前端开发工程师',
      topK: 5,
      evidence: [
        { nodeId: 'python', label: 'Python', score: 0.9, source: '压力测试', rawText: 'Python' },
        { nodeId: 'sql', label: 'SQL', score: 0.87, source: '压力测试', rawText: 'SQL' },
        { nodeId: 'cpp_gap', label: '不擅长 C++', score: 0.78, source: '压力测试', rawText: '不太擅长 C++' }
      ],
      tuning: {
        confidence: 0.64,
        exploration: 0.68,
        penaltyTolerance: 0.58
      }
    }
  },
  {
    id: 'sparse',
    label: '稀疏输入',
    description: '几乎没有明确技能信号',
    kind: 'stress',
    state: {
      text: '目前就是想看看自己适合什么方向，暂时没有特别明确的项目经历。',
      targetRole: '机器学习工程师',
      topK: 5,
      evidence: [],
      tuning: {
        confidence: 0.5,
        exploration: 0.82,
        penaltyTolerance: 0.6
      }
    }
  },
  {
    id: 'mixed',
    label: '中英混合',
    description: '英文缩写、符号和中文混写',
    kind: 'stress',
    state: {
      text: 'I have done frontend project, know SQL / Python, and want to keep doing Web dev with team communication.',
      targetRole: '前端开发工程师',
      topK: 5,
      evidence: [
        { nodeId: 'frontend_project', label: '前端项目', score: 0.88, source: '压力测试', rawText: 'frontend project' },
        { nodeId: 'communication', label: '沟通表达', score: 0.76, source: '压力测试', rawText: 'team communication' }
      ],
      tuning: {
        confidence: 0.66,
        exploration: 0.62,
        penaltyTolerance: 0.45
      }
    }
  }
] satisfies Array<{
  id: string;
  label: string;
  description: string;
  kind: 'normal' | 'stress';
  state: DemoState;
}>;

export const buildRobustnessReport = (state: DemoState): RobustnessReport => {
  const cases: RobustnessCaseResult[] = scenarioPresets
    .filter((item) => item.kind === 'stress')
    .map((preset) => {
      const evaluationState: DemoState = {
        ...preset.state,
        topK: state.topK,
        tuning: state.tuning
      };
      const baselineState: DemoState = {
        ...preset.state,
        topK: state.topK,
        tuning: defaultDemoState.tuning
      };
      const response = buildRecommendationResponse(evaluationState);
      const baselineResponse = buildRecommendationResponse(baselineState);
      const topCard = response.recommendations[0];
      const baselineTopCard = baselineResponse.recommendations[0];
      const topScore = topCard?.score ?? response.nearMissRoles[0]?.score ?? 0;
      const baselineTopScore = baselineTopCard?.score ?? baselineResponse.nearMissRoles[0]?.score ?? 0;
      const scoreDelta = topScore - baselineTopScore;
      const coverage = response.targetRoleAnalysis.coverage;
      const warningParts = [
        topCard ? `主推荐：${topCard.label}` : '没有正式推荐',
        baselineTopCard ? `默认权重：${baselineTopCard.label}` : '默认权重无正式推荐',
        response.nearMissRoles.length ? `near miss：${response.nearMissRoles.length}` : '无 near miss',
        coverage < 0.5 ? '目标岗位覆盖偏弱' : '目标岗位覆盖尚可'
      ];

      return {
        id: preset.id,
        label: preset.label,
        description: preset.description,
        topRole: topCard?.label ?? response.targetRoleAnalysis.label,
        topScore,
        baselineTopScore,
        scoreDelta,
        recommendationCount: response.recommendations.length,
        nearMissCount: response.nearMissRoles.length,
        coverage,
        warning: warningParts.join('；')
      };
    });

  const averageTopScore = cases.length ? cases.reduce((sum, item) => sum + item.topScore, 0) / cases.length : 0;
  const averageDelta = cases.length ? cases.reduce((sum, item) => sum + item.scoreDelta, 0) / cases.length : 0;
  const improvedCount = cases.filter((item) => item.scoreDelta > 0).length;
  const fragileCount = cases.filter((item) => item.topScore < 0.42 || item.recommendationCount === 0).length;
  const bestImprovement = [...cases].sort((left, right) => right.scoreDelta - left.scoreDelta)[0];
  const worstRegression = [...cases].sort((left, right) => left.scoreDelta - right.scoreDelta)[0];
  const tuningAdvice = [
    fragileCount > 0
      ? '优先提高探索权重，先把稀疏输入和中英混合输入的桥接建议稳住。'
      : '当前鲁棒性整体稳定，可以先保持探索权重不变。',
    worstRegression && worstRegression.scoreDelta < 0
      ? `重点检查「${worstRegression.label}」，必要时降低信心权重或收紧证据触发阈值。`
      : '当前没有明显退化场景，可以继续观察默认权重与当前权重的差异。',
    worstRegression?.id === 'conflict'
      ? '冲突输入仍有回落时，优先加强否定词识别和 blocker 抑制。'
      : '如果后续出现冲突输入回落，再补强否定词和抑制逻辑。'
  ];

  return {
    averageTopScore,
    averageDelta,
    improvedCount,
    fragileCount,
    bestImprovementLabel: bestImprovement ? bestImprovement.label : '暂无',
    bestImprovementDelta: bestImprovement?.scoreDelta ?? 0,
    worstRegressionLabel: worstRegression ? worstRegression.label : '暂无',
    worstRegressionDelta: worstRegression?.scoreDelta ?? 0,
    tuningAdvice,
    headline:
      fragileCount > 0
        ? `有 ${fragileCount} 个极端输入场景需要继续加固解析和权重，当前平均变化 ${Math.round(averageDelta * 100)}%`
        : `极端输入下整体表现稳定，当前平均变化 ${Math.round(averageDelta * 100)}%`,
    cases
  };
};

export const buildDiagnosticSnapshot = (
  activeStep: string,
  currentState: DemoState,
  recommendation: RecommendationResponse,
  robustness: RobustnessReport
): DiagnosticSnapshot => ({
  generatedAt: new Date().toISOString(),
  activeStep,
  currentState,
  recommendation,
  robustness
});

export const getRoleOptions = (): RoleOption[] => roleCatalog;

export const buildRecommendationResponse = (state: DemoState): RecommendationResponse => {
  const { evidenceMap, signalTrace } = analyzeInputText(state.text, state.evidence);
  const propagationSnapshot = buildPropagationSnapshot(evidenceMap, state.tuning);
  const scoredRoles = roleProfiles
    .map((profile) => scoreProfile(profile, evidenceMap, state.tuning))
    .sort((left, right) => right.score - left.score);
  const target = buildTargetAnalysis(state.targetRole, evidenceMap);
  const bridges = buildBridgeRecommendations(evidenceMap);
  // 正式推荐阈值略微放宽，保证正常画像能进入推荐区间，稀疏输入仍然保持保守。
  const recommendationThreshold = 0.5;
  const nearMissThreshold = 0.3;

  const recommendations = scoredRoles.filter((item) => item.score >= recommendationThreshold).slice(0, state.topK);
  const nearMissRoles = scoredRoles.filter((item) => item.score < recommendationThreshold && item.score >= nearMissThreshold).slice(0, 3);

  return {
    inputTrace: {
      rawText: state.text,
      targetRole: state.targetRole,
      resolvedTargetRole: target.label,
      structuredEvidence: state.evidence.map((item) => ({
        ...item,
        score: evidenceMap.get(item.nodeId) ?? item.score
      })),
      signalTrace
    },
    recommendations,
    nearMissRoles,
    bridgeRecommendations: bridges,
    targetRoleAnalysis: target,
    propagationSnapshot,
    graphSnapshot: {
      nodeCount: nodeCatalog.length,
      edgeCount: propagationSnapshot.edges.length,
      layerBreakdown: propagationSnapshot.layers.reduce<Record<string, number>>((accumulator, layer) => {
        accumulator[layer.layer] = layer.nodes.length;
        return accumulator;
      }, {})
    }
  };
};

export const getDemoCopy = (response: RecommendationResponse) => {
  const topRole = response.recommendations[0]?.label ?? response.targetRoleAnalysis.label;
  return {
    headline: `当前最适合的方向是 ${topRole}`,
    summary: response.recommendations.length
      ? `${response.recommendations[0].reason.join('，')}`
      : '当前输入信号偏弱，建议补充更明确的项目或技能证据。',
    targetLine: response.targetRoleAnalysis.gaps.length
      ? `目标岗位还缺少：${response.targetRoleAnalysis.gaps.join('、')}`
      : '目标岗位已经被较强覆盖。'
  };
};
