export interface SignalInput {
  entity: string;
  score: number;
}

export interface StructuredSignalDraft {
  id: string;
  entity: string;
  score: number;
}

export interface ConfirmedSignalDraft {
  id: string;
  nodeId: string;
  nodeName: string;
  score: number;
  source: string;
}

export interface NormalizedSignal {
  node_id: string;
  node_name: string;
  score: number;
  source: string;
}

export interface PathExplanation {
  score: number;
  node_ids: string[];
  labels: string[];
  relations: string[];
}

export interface SourceRef {
  profile_id: string;
  source_type: string;
  source_id: string;
  source_title: string;
  source_url: string;
  snapshot_date: string;
  evidence_snippet: string;
  sample_job_titles: string[];
}

export interface GapSuggestion {
  node_id: string;
  node_name: string;
  relation: string;
  current_score: number;
  tip: string;
}

export interface RecommendationItem {
  job_id: string;
  job_name: string;
  score: number;
  reason: string;
  paths: PathExplanation[];
  limitations: string[];
  provenance_count: number;
  source_type_count: number;
  source_types: string[];
  source_refs: SourceRef[];
}

export interface NearMissItem {
  job_id: string;
  job_name: string;
  near_miss_score: number;
  score: number;
  gap_summary: string;
  paths: PathExplanation[];
  limitations: string[];
  missing_requirements: string[];
  suggestions: GapSuggestion[];
  provenance_count: number;
  source_type_count: number;
  source_types: string[];
  source_refs: SourceRef[];
}

export interface BridgeRolePreview {
  job_id: string;
  job_name: string;
  score: number;
}

export interface BridgeRecommendationItem {
  anchor_id: string;
  anchor_name: string;
  anchor_type: string;
  bridge_score: number;
  score: number;
  summary: string;
  paths: PathExplanation[];
  limitations: string[];
  next_steps: GapSuggestion[];
  related_roles: BridgeRolePreview[];
  provenance_count: number;
  source_type_count: number;
  source_types: string[];
  source_refs: SourceRef[];
}

export interface GraphSnapshotNode {
  id: string;
  name: string;
  layer: string;
  node_type: string;
  description: string;
  score: number;
  aggregator: string;
  metadata: {
    provenance_count?: number;
    source_type_count?: number;
    source_types?: string[];
    source_refs?: SourceRef[];
    latest_snapshot_date?: string;
  };
  diagnostics: Record<string, unknown>;
}

export interface GraphSnapshotEdge {
  source: string;
  target: string;
  relation: string;
  value: number;
  note: string;
}

export interface PropagationSnapshot {
  nodes: GraphSnapshotNode[];
  edges: GraphSnapshotEdge[];
}

export interface GraphStats {
  node_count: number;
  edge_count: number;
  evidence_node_count?: number;
  role_count?: number;
  activated_node_count?: number;
  source_profile_count: number;
  nodes_with_provenance: number;
  source_types: string[];
  source_type_count: number;
  source_profile_count_by_type?: Record<string, number>;
  latest_snapshot_date?: string;
}

export interface RecommendationResponse {
  normalized_inputs: NormalizedSignal[];
  recommendations: RecommendationItem[];
  near_miss_roles: NearMissItem[];
  bridge_recommendations: BridgeRecommendationItem[];
  empty_result_reason: string | null;
  propagation_snapshot: PropagationSnapshot | null;
  parsing_notes: string[];
  parsing_debug: {
    rule_hits: unknown[];
    alias_hits: unknown[];
    unmatched_segments: string[];
    candidate_signals: unknown[];
    segments: string[];
  };
  unresolved_entities: string[];
  graph_stats: GraphStats;
}

export interface ActionCard {
  template_id: string;
  title: string;
  action_type: string;
  summary: string;
  effort_level: string;
  action_key: string;
  deliverables: string[];
  tags: string[];
  matched_node_ids: string[];
  matched_node_names: string[];
  simulation_node_ids: string[];
  reason: string;
}

export interface SimulatedBoost {
  node_id: string;
  node_name: string;
  from_score: number;
  to_score: number;
  tip: string;
}

export interface LearningPathStep {
  step: number;
  focus_node_id: string;
  focus_node_name: string;
  relation: string;
  title: string;
  summary: string;
  expected_score_delta: number;
  expected_total_score: number;
  blocked_by: string[];
  unlock_nodes: string[];
  boosts: SimulatedBoost[];
  recommended_actions: ActionCard[];
}

export interface SimulationScenario {
  title: string;
  predicted_score: number;
  delta_score: number;
  summary: string;
  boosts: SimulatedBoost[];
}

export interface TargetRoleAnalysis {
  job_id: string;
  job_name: string;
  current_score: number;
  gap_summary: string;
  paths: PathExplanation[];
  limitations: string[];
  missing_requirements: string[];
  priority_suggestions: GapSuggestion[];
  what_if_scenarios: SimulationScenario[];
  learning_path: LearningPathStep[];
  provenance_count: number;
  source_type_count: number;
  source_types: string[];
  source_refs: SourceRef[];
}

export interface RoleGapResponse {
  target_role: TargetRoleAnalysis;
  normalized_inputs: NormalizedSignal[];
  parsing_notes: string[];
  parsing_debug: RecommendationResponse["parsing_debug"];
  unresolved_entities: string[];
}

export interface ActionImpactNode {
  node_id: string;
  node_name: string;
  layer: string;
  before_score: number;
  after_score: number;
  delta_score: number;
}

export interface RoleScorePreview {
  job_id: string;
  job_name: string;
  score: number;
}

export interface ActionSimulationResult {
  target_role_id: string;
  target_role_name: string;
  action_keys: string[];
  template_ids: string[];
  bundle_size: number;
  current_score: number;
  predicted_score: number;
  delta_score: number;
  summary: string;
  bundle_summary: string;
  overlap_node_ids: string[];
  overlap_node_names: string[];
  applied_actions: ActionCard[];
  injected_boosts: SimulatedBoost[];
  activated_nodes: ActionImpactNode[];
  before_top_roles: RoleScorePreview[];
  after_top_roles: RoleScorePreview[];
  target_role_rank_before: number;
  target_role_rank_after: number;
}

export interface ActionSimulationResponse {
  simulation: ActionSimulationResult;
  normalized_inputs: NormalizedSignal[];
  parsing_notes: string[];
  parsing_debug: RecommendationResponse["parsing_debug"];
  unresolved_entities: string[];
}

export interface CatalogNode {
  id: string;
  name: string;
  node_type: string;
  description: string;
  aliases?: string[];
}

export interface DemoCase {
  id: string;
  title: string;
  summary: string;
  tags: string[];
  source: string;
  text: string;
  signals: SignalInput[];
  signal_count: number;
  target_role_id: string;
  target_role_name: string;
  preview: string;
}

export interface CatalogResponse {
  evidence_nodes: CatalogNode[];
  role_nodes: CatalogNode[];
  graph_stats: GraphStats;
  sample_request: {
    text: string;
    signals: SignalInput[];
    top_k?: number;
  };
  demo_cases: DemoCase[];
}

export type ResultCard =
  | ({ kind: "recommendation"; key: string } & RecommendationItem)
  | ({ kind: "near_miss"; key: string } & NearMissItem)
  | ({ kind: "bridge"; key: string } & BridgeRecommendationItem);

export interface SelectionState {
  kind: ResultCard["kind"];
  id: string;
}

export interface StatusState {
  busy: boolean;
  message: string;
  error: string;
}
