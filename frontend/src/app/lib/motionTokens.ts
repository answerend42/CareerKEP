export const motionDurations = {
  instant: 0.01,
  fast: 0.14,
  mid: 0.18,
  slow: 0.24,
} as const;

export const motionTimings = {
  layerRevealStepMs: 420,
  pathSegmentStepMs: 520,
} as const;

export const motionEase = {
  productive: [0.25, 1, 0.5, 1],
  expressive: [0.16, 1, 0.3, 1],
} as const;

export function pageTransitionFor(reducedMotion: boolean) {
  if (reducedMotion) {
    return {
      initial: { opacity: 0 },
      animate: { opacity: 1 },
      exit: { opacity: 0 },
      transition: { duration: motionDurations.instant, ease: "linear" },
    } as const;
  }

  return {
    initial: { opacity: 0, y: 8 },
    animate: { opacity: 1, y: 0, filter: "blur(0px)" },
    exit: { opacity: 0, y: -4 },
    transition: { duration: motionDurations.mid, ease: motionEase.expressive },
  } as const;
}
