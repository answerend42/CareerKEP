export interface EvidenceItem {
  nodeId: string;
  label: string;
  score: number;
  source: string;
  rawText: string;
}

export interface RoleOption {
  nodeId: string;
  label: string;
  searchTerms: string[];
}

export interface StageNode {
  id: string;
  label: string;
  layer: 'evidence' | 'ability' | 'composite' | 'direction' | 'role';
  score: number;
  detail: string;
}

export interface StageEdge {
  source: string;
  target: string;
  relation: string;
  contribution: number;
}

export interface RecommendationCard {
  nodeId: string;
  label: string;
  score: number;
  reason: string[];
  missing: string[];
  path: string[];
}

export interface BridgeCard {
  nodeId: string;
  label: string;
  score: number;
  why: string;
}

export interface TargetRoleAnalysis {
  nodeId: string;
  label: string;
  coverage: number;
  strengths: string[];
  gaps: string[];
  path: string[];
}

export interface RecommendationResponse {
  inputTrace: {
    rawText: string;
    targetRole: string;
    resolvedTargetRole: string;
    structuredEvidence: EvidenceItem[];
  };
  recommendations: RecommendationCard[];
  nearMissRoles: RecommendationCard[];
  bridgeRecommendations: BridgeCard[];
  targetRoleAnalysis: TargetRoleAnalysis;
  propagationSnapshot: {
    layers: {
      layer: StageNode['layer'];
      label: string;
      nodes: StageNode[];
    }[];
    edges: StageEdge[];
  };
  graphSnapshot: {
    nodeCount: number;
    edgeCount: number;
    layerBreakdown: Record<string, number>;
  };
}

export interface TuningState {
  confidence: number;
  exploration: number;
  penaltyTolerance: number;
}

export interface DemoState {
  text: string;
  targetRole: string;
  topK: number;
  evidence: EvidenceItem[];
  tuning: TuningState;
}

export interface ScenarioPreset {
  id: string;
  label: string;
  description: string;
  kind: 'normal' | 'stress';
  state: DemoState;
}

export interface RobustnessCaseResult {
  id: string;
  label: string;
  description: string;
  topRole: string;
  topScore: number;
  recommendationCount: number;
  nearMissCount: number;
  coverage: number;
  warning: string;
}

export interface RobustnessReport {
  averageTopScore: number;
  fragileCount: number;
  headline: string;
  cases: RobustnessCaseResult[];
}
