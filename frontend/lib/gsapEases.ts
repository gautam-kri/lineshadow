import gsap from "gsap";
import { CustomEase } from "gsap/CustomEase";
import { ScrollTrigger } from "gsap/ScrollTrigger";

/**
 * Registers GSAP plugins and the named eases Zone A uses.
 *
 * GSAP does *not* parse CSS `cubic-bezier(...)` strings -- `gsap.parseEase()`
 * returns undefined for them and the tween silently falls back to the default
 * ease. So every curve from the motion-design tables is registered through
 * CustomEase by name instead, which is the only way to actually get the
 * specified curve rather than something that looks approximately like it.
 *
 * Import `registerNarrativeGsap()` before using these names.
 */

/** motion-design Premium archetype: 350-600ms companion, zero overshoot. */
export const EASE_PREMIUM = "nj-premium";
/** animate's strong ease-out, for anything entering or exiting. */
export const EASE_OUT_STRONG = "nj-out";

let registered = false;

export function registerNarrativeGsap(): void {
  if (registered) return;
  gsap.registerPlugin(ScrollTrigger, CustomEase);
  CustomEase.create(EASE_PREMIUM, "0.4, 0, 0.2, 1");
  CustomEase.create(EASE_OUT_STRONG, "0.23, 1, 0.32, 1");
  registered = true;
}

export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
