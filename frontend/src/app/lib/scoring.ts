export const SCORE_OPTIONS = [
  { label: "弱", value: 0.18 },
  { label: "入门", value: 0.35 },
  { label: "中等", value: 0.55 },
  { label: "熟悉", value: 0.75 },
  { label: "扎实", value: 0.92 },
] as const;

export const ACTION_TYPE_LABELS: Record<string, string> = {
  project: "项目",
  practice: "练习",
  course: "课程",
  portfolio: "作品集",
};

export const EFFORT_LEVEL_LABELS: Record<string, string> = {
  low: "低投入",
  medium: "中投入",
  high: "高投入",
};

export const SOURCE_TYPE_LABELS: Record<string, string> = {
  onet_online: "O*NET",
  roadmap_sh: "roadmap.sh",
};

export function clampScore(value: number): number {
  return Math.max(0, Math.min(1, value));
}

export function formatPercent(value: number): string {
  return `${Math.round(clampScore(value) * 100)}`;
}

export function formatSignedPercent(value: number): string {
  const rounded = Math.round(value * 100);
  return `${rounded >= 0 ? "+" : ""}${rounded}`;
}

export function sourceTypeLabel(sourceType: string): string {
  return SOURCE_TYPE_LABELS[sourceType] || sourceType;
}

export function bandFromScore(score: number): number {
  let activeIndex = 0;
  for (const [index, option] of SCORE_OPTIONS.entries()) {
    if (score >= option.value) {
      activeIndex = index;
    }
  }
  return activeIndex;
}
