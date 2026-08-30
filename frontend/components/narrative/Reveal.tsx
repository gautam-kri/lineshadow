"use client";

import { useRef, type ReactNode } from "react";
import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { EASE_PREMIUM, prefersReducedMotion, registerNarrativeGsap } from "@/lib/gsapEases";

registerNarrativeGsap();
gsap.registerPlugin(useGSAP);

/**
 * Discrete scroll reveal for a group of children.
 *
 * Zone A. Premium archetype: 500ms on the registered Premium curve, no
 * overshoot. Discrete rather than scrubbed, because this content should settle
 * and stay settled -- scrub is reserved for the two scenes where the motion
 * genuinely *is* the scroll.
 *
 * Stagger uses GSAP's native stagger, never a manual per-element delay loop, and
 * stays inside motion-design's standard budget: 50-100ms per item, under 400ms
 * total. `once: true` kills the trigger after firing so nothing keeps running.
 *
 * Reduced motion cross-fades in place with no travel.
 */

interface Props {
  children: ReactNode;
  /** Seconds between siblings. Standard budget is 0.05-0.1. */
  stagger?: number;
  className?: string;
}

export function Reveal({ children, stagger = 0.08, className }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      const node = ref.current;
      if (!node) return;
      const items = gsap.utils.toArray<HTMLElement>(node.children);
      if (!items.length) return;

      const reduce = prefersReducedMotion();

      gsap.from(items, {
        opacity: 0,
        y: reduce ? 0 : 18,
        duration: reduce ? 0.2 : 0.5,
        ease: reduce ? "none" : EASE_PREMIUM,
        stagger: reduce ? 0 : stagger,
        scrollTrigger: { trigger: node, start: "top 82%", once: true },
      });
    },
    { scope: ref },
  );

  return (
    <div ref={ref} className={className}>
      {children}
    </div>
  );
}
