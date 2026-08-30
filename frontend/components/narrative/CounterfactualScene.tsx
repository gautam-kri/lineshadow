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
 * longer dramatic reveal is correct, so the timeline is scrubbed to the scroll
 * rather than fired discretely -- the viewer controls the pace.
 *
 * HOLDING TECHNIQUE: a tall track with a `position: sticky` child, NOT
 * ScrollTrigger's `pin`. Pinning works by injecting a spacer element and sizing
 * it to the pin duration; when that sizing does not take, the following section
 * scrolls straight over the fixed one. Sticky delegates the same behaviour to
 * the layout engine, where the track's own height reserves the space and an
 * overlap is structurally impossible. ScrollTrigger is then only responsible for
 * scrubbing the timeline, which is the part it is actually good at.
 *
 * This is also the one place `clip-path` is sanctioned as a fourth animated
 * property: drawing a line by wiping a reveal mask is genuinely not expressible
 * as transform or opacity, and animating `width` would trigger layout per frame.
 */

const W = 900;
const H = 300;
const SPLIT = 0.46; // fraction of the width where the fault is injected

// Drawn as three paths, not two. If the faulted run were one continuous path it
// would paint over the shared segment and the "identical until the fault" half
// of the story would read as red -- i.e. as though only one run existed early on.
// A neutral shared trunk that fans into two branches says it correctly.
const TRUNK = `M 40 ${H / 2} C 180 ${H / 2 - 18}, 300 ${H / 2 + 14}, ${W * SPLIT} ${H / 2}`;
const BRANCH_CLEAN = `M ${W * SPLIT} ${H / 2} C 620 ${H / 2 - 12}, 740 ${H / 2 + 10}, ${W - 40} ${H / 2}`;
const BRANCH_FAULTED = `M ${W * SPLIT} ${H / 2} C 620 ${H / 2 + 30}, 700 ${H / 2 + 74}, ${W - 40} ${H / 2 + 96}`;

export function CounterfactualScene() {
  const root = useRef<HTMLElement>(null);

  useGSAP(
    () => {
      const node = root.current;
      if (!node) return;
      const reduce = prefersReducedMotion();

      const wipe = node.querySelector<SVGRectElement>("[data-wipe]");
      const split = node.querySelector<SVGGElement>("[data-split]");
      const gap = node.querySelector<SVGGElement>("[data-gap]");
      if (!wipe || !split || !gap) return;

      if (reduce) {
        // No scrub, no sticky (dropped in CSS). The scene is simply present and
        // correct, and reads as a static diagram.
        gsap.set(wipe, { attr: { width: W } });
        gsap.set([split, gap], { opacity: 1 });
        return;
      }

      gsap.set([split, gap], { opacity: 0 });

      const tl = gsap.timeline({
        scrollTrigger: {
          trigger: node,
          // The track is 240vh and the sticky child is 100vh, so the scene holds
          // for 140vh of scrolling. Scrubbing across exactly that range keeps
          // the animation and the hold in lockstep with no spacer arithmetic.
          start: "top top",
          end: "bottom bottom",
          scrub: 0.6,
        },
      });

      // The wipe alone reveals the divergence -- the geometry is the drama, so
      // the branches need no separate fade on top of it.
      tl.to(wipe, { attr: { width: W * SPLIT }, ease: "none", duration: 1 })
        .to(split, { opacity: 1, duration: 0.35, ease: EASE_PREMIUM }, ">-0.1")
        .to(wipe, { attr: { width: W }, ease: "none", duration: 1.2 })
        .to(gap, { opacity: 1, duration: 0.4, ease: EASE_PREMIUM }, ">-0.3");
    },
    { scope: root },
  );

  return (
    <section ref={root} className="nj-scene-track relative h-[240vh]">
      <div className="nj-scene-sticky sticky top-0 flex h-screen flex-col justify-center overflow-hidden">
        <div className="mx-auto w-full max-w-4xl px-6">
          <p className="nj-label">The counterfactual</p>
          <h2 className="font-display mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
            Same seed. Same random draws. One fault.
          </h2>
          <p className="mt-4 max-w-2xl text-sm leading-relaxed text-dim">
            Every scenario runs twice. Both runs share their per-unit random draws, so the two
            traces are identical until the fault is injected — and everything after the split is
            attributable to that fault and nothing else. That is how &ldquo;37 minutes
            early&rdquo; is a measured fact rather than an estimate.
          </p>

          <svg
            viewBox={`0 0 ${W} ${H + 40}`}
            className="mt-8 w-full"
            role="img"
            aria-label="A single shared trace representing two simulation runs from the same seed. At the point the fault is injected it splits into two branches: the counterfactual run continues flat, while the faulted run degrades below it. The vertical gap between the branches is the throughput lost to the fault."
          >
            <defs>
              <clipPath id="nj-cf-wipe">
                <rect data-wipe x="0" y="0" width="0" height={H + 40} />
              </clipPath>
            </defs>

            <g clipPath="url(#nj-cf-wipe)">
              {/* Shared trunk: both runs, indistinguishable. */}
              <path d={TRUNK} fill="none" stroke="var(--nj-dim)" strokeWidth={2.5} strokeLinecap="round" />
              <path d={BRANCH_CLEAN} fill="none" stroke="var(--nj-healthy)" strokeWidth={2.5} strokeLinecap="round" />
              <path d={BRANCH_FAULTED} fill="none" stroke="var(--nj-critical)" strokeWidth={2.5} strokeLinecap="round" />
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

            <text x={40} y={H / 2 - 16} fontSize={13} fill="var(--nj-dim)">
              both runs, same seed
            </text>
            <text x={W * SPLIT + 150} y={H / 2 - 12} fontSize={13} fill="var(--nj-healthy)">
              counterfactual — no fault
            </text>
            <text x={W * SPLIT + 150} y={H / 2 + 82} fontSize={13} fill="var(--nj-critical)">
              faulted run
            </text>
          </svg>
        </div>
      </div>
    </section>
  );
}
