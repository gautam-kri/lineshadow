"use client";

import { useRef } from "react";
import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { EASE_PREMIUM, prefersReducedMotion, registerNarrativeGsap } from "@/lib/gsapEases";

registerNarrativeGsap();
gsap.registerPlugin(useGSAP);

/**
 * The counterfactual explainer -- the most important animated explanation here.
 *
 * Two runs of the same seed trace one identical path, then split at the fault
 * point. The gap between them is the whole methodology: because both runs share
 * their per-unit random draws, everything after the split is attributable to the
 * fault and nothing else.
 *
 * Gate: rare / first-time tier, purpose is Explanation. That is the tier where a
 * longer dramatic reveal is correct, so this is scrubbed to the scroll rather
 * than fired discretely -- the viewer controls the pace of the explanation.
 *
 * This is the one place `clip-path` is sanctioned as a fourth animated property:
 * drawing a line by wiping a reveal mask is genuinely not expressible as
 * transform or opacity, and animating `width` instead would trigger layout on
 * every frame.
 */

const W = 900;
const H = 300;
const SPLIT = 0.46; // fraction of the width where the fault is injected

/** Shared path up to the split, then the two runs diverge. */
const COMMON = `M 40 ${H / 2} C 180 ${H / 2 - 18}, 300 ${H / 2 + 14}, ${W * SPLIT} ${H / 2}`;
const COUNTERFACTUAL = `${COMMON} C 620 ${H / 2 - 12}, 740 ${H / 2 + 10}, ${W - 40} ${H / 2}`;
const FAULTED = `${COMMON} C 620 ${H / 2 + 30}, 700 ${H / 2 + 74}, ${W - 40} ${H / 2 + 96}`;

export function CounterfactualScene() {
  const root = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      const node = root.current;
      if (!node) return;
      const reduce = prefersReducedMotion();

      const wipe = node.querySelector<SVGRectElement>("[data-wipe]");
      const split = node.querySelector<SVGGElement>("[data-split]");
      const gap = node.querySelector<SVGGElement>("[data-gap]");
      const faulted = node.querySelector<SVGPathElement>("[data-faulted]");
      if (!wipe || !split || !gap || !faulted) return;

      if (reduce) {
        // Reduced motion: no pinning, no scrub. The scene is simply present and
        // correct, and the section cross-fades in like every other one.
        gsap.set(wipe, { attr: { width: W } });
        gsap.set([split, gap, faulted], { opacity: 1 });
        return;
      }

      gsap.set([split, gap], { opacity: 0 });
      gsap.set(faulted, { opacity: 0 });

      const tl = gsap.timeline({
        scrollTrigger: {
          trigger: node,
          start: "top top",
          end: "+=1400",
          // Pinned and scrubbed: the viewer scrubs the explanation at their own
          // pace. Only two sections in Zone A are pinned, and this is one.
          pin: true,
          scrub: 0.6,
          anticipatePin: 1,
        },
      });

      // The wipe is a clip mask over both paths, so "drawing" them costs no
      // layout: it is a single rect width attribute driving a clipPath.
      tl.to(wipe, { attr: { width: W * SPLIT }, ease: "none", duration: 1 })
        .to(split, { opacity: 1, duration: 0.35, ease: EASE_PREMIUM }, ">-0.1")
        .to(faulted, { opacity: 1, duration: 0.3, ease: EASE_PREMIUM }, "<")
        .to(wipe, { attr: { width: W }, ease: "none", duration: 1.2 })
        .to(gap, { opacity: 1, duration: 0.4, ease: EASE_PREMIUM }, ">-0.3");
    },
    { scope: root },
  );

  return (
    <div ref={root} className="flex min-h-screen flex-col justify-center py-16">
      <div className="mx-auto w-full max-w-4xl px-6">
        <p className="nj-label">The counterfactual</p>
        <h2 className="font-display mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
          Same seed. Same random draws. One fault.
        </h2>
        <p className="mt-4 max-w-2xl text-sm leading-relaxed text-dim">
          Every scenario runs twice. Both runs share their per-unit random draws, so the two
          traces are identical until the fault is injected — and everything after the split is
          attributable to that fault and nothing else. That is how &ldquo;37 minutes early&rdquo;
          is a measured fact rather than an estimate.
        </p>

        <svg
          viewBox={`0 0 ${W} ${H + 40}`}
          className="mt-8 w-full"
          role="img"
          aria-label="Two simulation runs from the same seed follow an identical path until a fault is injected, after which the faulted run degrades away from the counterfactual. The vertical gap between them is the throughput lost to the fault."
        >
          <defs>
            <clipPath id="nj-cf-wipe">
              <rect data-wipe x="0" y="0" width="0" height={H + 40} />
            </clipPath>
          </defs>

          <g clipPath="url(#nj-cf-wipe)">
            <path
              d={COUNTERFACTUAL}
              fill="none"
              stroke="var(--nj-healthy)"
              strokeWidth={2.5}
              strokeLinecap="round"
            />
            <path
              data-faulted
              d={FAULTED}
              fill="none"
              stroke="var(--nj-critical)"
              strokeWidth={2.5}
              strokeLinecap="round"
            />
          </g>

          <g data-split>
            <line
              x1={W * SPLIT}
              x2={W * SPLIT}
              y1={40}
              y2={H + 10}
              stroke="var(--nj-border-strong)"
              strokeDasharray="4 4"
            />
            <text x={W * SPLIT + 10} y={58} fontSize={13} fill="var(--nj-dim)">
              fault injected
            </text>
          </g>

          <g data-gap>
            <line
              x1={W - 70}
              x2={W - 70}
              y1={H / 2}
              y2={H / 2 + 96}
              stroke="var(--nj-warning)"
              strokeWidth={1.5}
            />
            <text
              x={W - 82}
              y={H / 2 + 54}
              fontSize={13}
              fill="var(--nj-warning)"
              textAnchor="end"
            >
              throughput lost to the fault
            </text>
          </g>

          <text x={40} y={H / 2 - 16} fontSize={13} fill="var(--nj-healthy)">
            counterfactual — no fault
          </text>
          <text x={40} y={H + 30} fontSize={13} fill="var(--nj-critical)">
            faulted run
          </text>
        </svg>
      </div>
    </div>
  );
}
