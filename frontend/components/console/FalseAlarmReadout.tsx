"use client";

import { useEffect, useState } from "react";
import { motion, useMotionValue, useReducedMotion, useSpring } from "motion/react";

/**
 * The live false-alarms-per-shift figure.
 *
 * This is the proof-of-tradeoff moment: drag the sensitivity up and watch what
 * it costs. It has to feel instant, so the value is interpolated from the sealed
 * holdout sweep on the client and never waits on a network round trip.
 *
 * MOTION. Gate: continuous during a drag, purpose is feedback. A spring rather
 * than a tween because the user can reverse mid-drag and a spring carries
 * velocity through the interruption -- the animate skill's stated case for one.
 * Bounce is zero: a false-alarm count that overshoots its real value would be
 * actively misleading, which is a correctness question, not a taste one.
 */

interface Props {
  value: number | null;
  caption: string;
}

export function FalseAlarmReadout({ value, caption }: Props) {
  const reduce = useReducedMotion();
  const raw = useMotionValue(value ?? 0);
  const spring = useSpring(raw, { stiffness: 220, damping: 32, mass: 0.6 });
  const [shown, setShown] = useState(value ?? 0);

  useEffect(() => {
    if (value === null) return;
    if (reduce) {
      // Reduced motion: land on the number immediately. The figure still
      // updates, it just does not travel to get there.
      setShown(value);
      raw.set(value);
      return;
    }
    raw.set(value);
  }, [value, raw, reduce]);

  useEffect(() => {
    if (reduce) return;
    return spring.on("change", (v) => setShown(v));
  }, [spring, reduce]);

  if (value === null) return null;

  return (
    <div className="min-w-52">
      <span className="nj-label">Expected false alarms / shift</span>
      <motion.div className="tnum mt-1 text-3xl font-semibold tracking-tight">
        {shown.toFixed(2)}
      </motion.div>
      <span className="text-[0.72rem] text-mute">{caption}</span>
    </div>
  );
}
