"use client";

import { useRef } from "react";
import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { EASE_PREMIUM, prefersReducedMotion, registerNarrativeGsap } from "@/lib/gsapEases";

registerNarrativeGsap();
gsap.registerPlugin(useGSAP);

/**
 * The differentiator: what happens when a station's neighbours go dark.
 *
 * Gate: rare / first-time tier, purpose is Explanation. This is the single most
 * important visual moment on the page, so it gets room -- 700ms, comfortably
 * above the 500ms floor, on the Premium curve.
 *
 * The band widens by scaling a rect on its own vertical centre, so the whole
 * beat stays on transform and opacity. Discrete rather than scrubbed: this is a
 * before/after comparison, and it should land and hold rather than being
 * scrubbable back into an unresolved state.
 */

const STATIONS = 9;
const CENTRE = 4; // the station that loses its sensors

export function SparseSensorScene() {
  const root = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      const node = root.current;
      if (!node) return;
      const reduce = prefersReducedMotion();

      const lost = gsap.utils.toArray<SVGElement>(node.querySelectorAll("[data-lost]"));
      const band = node.querySelector<SVGRectElement>("[data-band]");
      const label = node.querySelector<SVGTextElement>("[data-conf]");
      if (!band || !label) return;

      const tl = gsap.timeline({
        scrollTrigger: { trigger: node, start: "top 65%", once: true },
      });

      if (reduce) {
        // No travel and no scaling drama: state the end condition directly.
        tl.set(lost, { opacity: 0.18 }).set(band, { scaleY: 3.4 }).set(label, { opacity: 1 });
        return;
      }

      // Lead with the hero: the sensors going dark is the cause, so it happens
      // first and alone. The band responds after, and the label lands last.
      tl.to(lost, { opacity: 0.18, duration: 0.4, ease: EASE_PREMIUM, stagger: 0.06 })
        .to(band, { scaleY: 3.4, duration: 0.7, ease: EASE_PREMIUM }, ">-0.1")
        .to(label, { opacity: 1, duration: 0.4, ease: EASE_PREMIUM }, ">-0.35");
    },
    { scope: root },
  );

  return (
    <div ref={root} className="mx-auto w-full max-w-4xl px-6 py-20">
      <p className="nj-label">The hard part</p>
      <h2 className="font-display mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
        14 of 40 stations have no sensors at all.
      </h2>
      <p className="mt-4 max-w-2xl text-sm leading-relaxed text-dim">
        When a station goes dark, Ninja infers it from the timing of its nearest instrumented
        neighbours. The estimate survives — but it arrives with a visibly wider uncertainty band
        and a lower confidence score.{" "}
        <strong className="text-fg">A station the twin cannot see never renders as green.</strong>
      </p>

      <svg
        viewBox="0 0 720 240"
        className="mt-10 w-full"
        role="img"
        aria-label="A row of nine instrumented stations. When the neighbours either side of the middle station lose their sensors, that station's uncertainty band widens roughly threefold and its confidence drops from high to low."
      >
        {Array.from({ length: STATIONS }, (_, i) => {
          const x = 70 + i * 72;
          const isCentre = i === CENTRE;
          const isNeighbour = i === CENTRE - 1 || i === CENTRE + 1;
          return (
            <g key={i}>
              <line x1={x} x2={x} y1={92} y2={148} stroke="var(--nj-grid)" strokeWidth={1} />
              {isCentre ? (
                <>
                  {/* Band scales about its own centre, so this stays a transform. */}
                  <rect
                    data-band
                    x={x - 4}
                    y={112}
                    width={8}
                    height={16}
                    rx={3}
                    fill="var(--nj-band-inferred)"
                    style={{ transformBox: "fill-box", transformOrigin: "center" }}
                  />
                  <rect
                    x={x - 9}
                    y={111}
                    width={18}
                    height={18}
                    rx={2}
                    transform={`rotate(45 ${x} 120)`}
                    fill="none"
                    stroke="var(--nj-caution)"
                    strokeWidth={2.5}
                  />
                </>
              ) : (
                <circle
                  {...(isNeighbour ? { "data-lost": true } : {})}
                  cx={x}
                  cy={120}
                  r={7}
                  fill="var(--nj-healthy)"
                  stroke="var(--nj-border-strong)"
                  strokeWidth={1.5}
                />
              )}
            </g>
          );
        })}

        <text
          data-conf
          x={70 + CENTRE * 72}
          y={196}
          fontSize={13}
          fill="var(--nj-warning)"
          textAnchor="middle"
          opacity={0}
        >
          confidence: high → low · band ~3× wider
        </text>
      </svg>
    </div>
  );
}
