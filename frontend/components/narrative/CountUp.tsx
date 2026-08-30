"use client";

import { useRef } from "react";
import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

gsap.registerPlugin(ScrollTrigger, useGSAP);

/**
 * A headline figure that counts up once, on first scroll into view.
 *
 * Zone A only. This is the rare / first-time tier, where the delight budget
 * lives, and the purpose is state reveal -- so ease-out over ~800ms, and `once`
 * so it never replays. In Zone B the same numbers are static: a judge
 * re-reading a figure to fact-check it must not have to wait for it again.
 *
 * Under reduced motion the final value is rendered immediately.
 */

interface Props {
  value: number;
  decimals?: number;
  prefix?: string;
  suffix?: string;
  className?: string;
}

export function CountUp({ value, decimals = 0, prefix = "", suffix = "", className }: Props) {
  const ref = useRef<HTMLSpanElement>(null);

  useGSAP(
    () => {
      const node = ref.current;
      if (!node) return;

      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      const render = (v: number) => {
        node.textContent = `${prefix}${v.toFixed(decimals)}${suffix}`;
      };

      if (reduce) {
        render(value);
        return;
      }

      const counter = { v: 0 };
      render(0);
      gsap.to(counter, {
        v: value,
        duration: 0.8,
        ease: "power2.out",
        onUpdate: () => render(counter.v),
        scrollTrigger: { trigger: node, start: "top 85%", once: true },
      });
    },
    { scope: ref, dependencies: [value, decimals, prefix, suffix] },
  );

  // Server-rendered content is the final value, so the figure is correct with
  // JS disabled and for anything reading the DOM rather than watching it.
  return (
    <span ref={ref} className={className}>
      {`${prefix}${value.toFixed(decimals)}${suffix}`}
    </span>
  );
}
