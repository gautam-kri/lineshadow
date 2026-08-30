/**
 * Motion tokens. Single source of truth for both zones.
 *
 * ---------------------------------------------------------------------------
 * THE TWO BUDGETS CONFLICT ON PURPOSE. DO NOT UNIFY THEM.
 *
 * Zone A (the narrative shell, `/`) is seen once per viewer, so it follows
 * motion-design's Premium archetype: 350-600ms, cubic-bezier(0.4, 0, 0.2, 1),
 * zero overshoot. Cinematic is correct there.
 *
 * Zone B (the console, `/console`) is seen continuously during real use, so it
 * follows the animate skill's UI rule instead: under 300ms, and most feedback
 * well under that. Anything cinematic here becomes an obstacle.
 *
 * A 500ms curve is right in Zone A and a defect in Zone B. If you find yourself
 * "fixing" the inconsistency, read this comment again.
 * ---------------------------------------------------------------------------
 *
 * Every value below is taken from the animate and motion-design tables. None are
 * hand-rolled.
 */

/** Strong ease-out for UI. Entrances and exits. (animate) */
export const EASE_OUT = [0.23, 1, 0.32, 1] as const;
/** Strong ease-in-out for movement already on screen. (animate) */
export const EASE_IN_OUT = [0.77, 0, 0.175, 1] as const;
/** motion-design Premium signature curve. Zone A only. */
export const EASE_PREMIUM = [0.4, 0, 0.2, 1] as const;

export const DURATION = {
  /** Colour and hover feedback. Near-imperceptible tier. */
  instant: 0.16,
  /** Alert entering the feed. Standard feedback tier. */
  enter: 0.22,
  /** Exits run shorter than entrances: users care about what appears. */
  exit: 0.18,
  /** Result card arriving after a real network round trip. */
  reveal: 0.26,
} as const;

/**
 * Spring for the sensitivity readout.
 *
 * This is a value the user drags continuously, so it needs to carry velocity
 * through an interruption -- the animate skill's stated case for a spring over a
 * tween. Bounce stays at 0 because a false-alarm count overshooting its real
 * value would be actively misleading.
 */
export const COUNTER_SPRING = { stiffness: 220, damping: 32, mass: 0.6 } as const;

/**
 * Stagger between alert rows. Micro-cascade budget from motion-design
 * (20-40ms, total under 200ms), so ~6 visible rows stay inside the budget.
 */
export const ALERT_STAGGER = 0.03;

/** Shared enter/exit for feed rows. Exit mirrors the entrance path exactly. */
export const alertVariants = {
  initial: { opacity: 0, transform: "translateY(-6px)" },
  animate: { opacity: 1, transform: "translateY(0px)" },
  exit: { opacity: 0, transform: "translateY(-6px)" },
};
