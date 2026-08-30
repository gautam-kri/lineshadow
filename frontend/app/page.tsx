import Link from "next/link";
import { CountUp } from "@/components/narrative/CountUp";
import { Reveal } from "@/components/narrative/Reveal";
import { CounterfactualScene } from "@/components/narrative/CounterfactualScene";
import { SparseSensorScene } from "@/components/narrative/SparseSensorScene";

/**
 * Zone A -- the narrative shell.
 *
 * Seen once per viewer, so this is the one place in the build where the delight
 * budget applies and motion-design's Premium archetype governs: 350-600ms on
 * cubic-bezier(0.4, 0, 0.2, 1), zero overshoot. Zone B is under 300ms and stays
 * that way. See lib/motion.ts.
 *
 * Only two sections pin: the counterfactual explainer, where the viewer is
 * scrubbing an explanation, and nothing else. Every other section is a discrete
 * reveal that lands and holds.
 *
 * The honesty content -- the simulated-data disclaimer and the sealed-versus-
 * tuning distinction -- is deliberately static and always readable. Motion is
 * for delight and feedback, not for softening the parts a sceptic came to read.
 */

const FIGURES = [
  { value: 37, decimals: 0, prefix: "+", suffix: " min", label: "median lead time", sub: "before the queue forms" },
  { value: 99.2, decimals: 1, suffix: "%", label: "defect containment", sub: "caught before final inspection" },
  { value: 5.5, decimals: 1, label: "false alarms / shift", sub: "across 40 stations" },
];

export default function Home() {
  return (
    <>
      {/* 1 — Hero */}
      <section className="mx-auto flex min-h-screen w-full max-w-5xl flex-col justify-center px-6">
        <Reveal stagger={0.1}>
          <div className="flex items-baseline gap-2.5">
            <span className="text-2xl text-accent">◧</span>
            <span className="font-display text-2xl font-semibold tracking-tight">Ninja</span>
          </div>

          <h1 className="font-display mt-8 max-w-3xl text-4xl leading-[1.1] font-semibold tracking-tight sm:text-6xl">
            A digital twin that sees the bottleneck{" "}
            <span className="text-accent">37 minutes</span> before the line backs up.
          </h1>

          <p className="mt-7 max-w-xl text-base leading-relaxed text-dim">
            A 40-station mixed-model vehicle assembly line. Only 26 of the 40 stations have
            sensors, and buffer levels are never reported anywhere. Ninja reads the event stream,
            infers what it cannot see, and calls it early.
          </p>
        </Reveal>

        <Reveal stagger={0.09} className="mt-14 grid grid-cols-1 gap-8 sm:grid-cols-3">
          {FIGURES.map((f) => (
            <div key={f.label}>
              <div className="font-display tnum text-4xl font-semibold tracking-tight text-fg sm:text-5xl">
                <CountUp
                  value={f.value}
                  decimals={f.decimals}
                  prefix={f.prefix}
                  suffix={f.suffix}
                />
              </div>
              <div className="mt-2 text-sm text-fg">{f.label}</div>
              <div className="text-[0.75rem] text-mute">{f.sub}</div>
            </div>
          ))}
        </Reveal>

        <p className="mt-10 max-w-xl text-[0.78rem] leading-relaxed text-mute">
          All figures from sealed holdout scenarios scored against a frozen config — scenarios the
          system was never tuned against.
        </p>
      </section>

      {/* 2 — The problem */}
      <section className="mx-auto w-full max-w-5xl px-6 py-24">
        <p className="nj-label">The problem</p>
        <h2 className="font-display mt-3 max-w-2xl text-3xl font-semibold tracking-tight sm:text-4xl">
          Two things go wrong, and both are reported too late.
        </h2>
        <Reveal stagger={0.09} className="mt-10 grid gap-6 md:grid-cols-2">
          <article className="rounded-xl border border-line bg-elev p-6">
            <h3 className="text-base font-semibold text-fg">A station drifts</h3>
            <p className="mt-3 text-sm leading-relaxed text-dim">
              Cycle time creeps up over hours. Nobody notices until a queue has already formed
              downstream and the line is losing units. By then the warning is a report, not a
              chance to act.
            </p>
          </article>
          <article className="rounded-xl border border-line bg-elev p-6">
            <h3 className="text-base font-semibold text-fg">A defect escapes</h3>
            <p className="mt-3 text-sm leading-relaxed text-dim">
              A torque tool trends out of tolerance. The cars it builds pass every local check and
              fail dozens of units later at final inspection — after the process has already
              produced a batch of them.
            </p>
          </article>
        </Reveal>
      </section>

      {/* 3 — The counterfactual (pinned, scrubbed) */}
      <CounterfactualScene />

      {/* 4 — The three layers */}
      <section className="mx-auto w-full max-w-5xl px-6 py-24">
        <p className="nj-label">Three layers</p>
        <h2 className="font-display mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
          Detect, project, contain.
        </h2>
        <Reveal stagger={0.1} className="mt-10 space-y-4">
          {[
            {
              tag: "L1",
              title: "Drift detection",
              body: "EWMA + CUSUM per station per signal, self-calibrated on each station's own warm-up. Emits a continuous severity; nothing is thresholded inside the detector.",
            },
            {
              tag: "L2",
              title: "Bottleneck propagation",
              body: "Deterministic queueing arithmetic, not a nested simulation. A station below its feed rate fills its buffer at a computable rate, so time-to-saturation is division. Blocks walk upstream, starves walk downstream.",
            },
            {
              tag: "L3",
              title: "Defect escapes",
              body: "Inspection labels only exist after units reach station 40, so the primary path is unsupervised and available from unit one. A classifier calibrates as labels arrive, but it sharpens the score and never gates it.",
            },
          ].map((layer) => (
            <article
              key={layer.tag}
              className="flex gap-5 rounded-xl border border-line bg-elev p-6"
            >
              <span className="font-display text-lg font-semibold text-accent">{layer.tag}</span>
              <div>
                <h3 className="text-base font-semibold text-fg">{layer.title}</h3>
                <p className="mt-2 max-w-2xl text-sm leading-relaxed text-dim">{layer.body}</p>
              </div>
            </article>
          ))}
        </Reveal>
      </section>

      {/* 5 — Sparse-sensor differentiator */}
      <SparseSensorScene />

      {/* 6 — CTA into Zone B */}
      <section className="mx-auto w-full max-w-5xl px-6 py-28">
        <Reveal stagger={0.08}>
          <h2 className="font-display max-w-2xl text-3xl font-semibold tracking-tight sm:text-4xl">
            Open the console and inject a fault yourself.
          </h2>
          <p className="mt-4 max-w-xl text-sm leading-relaxed text-dim">
            The perturbation panel runs a fresh simulation, its same-seed counterfactual, and the
            twin — then scores the result with the same matching rule as the holdout report.
            Nothing in it is canned.
          </p>
          <div className="mt-8">
            <Link
              href="/console"
              className="inline-block rounded-lg bg-accent px-6 py-3 text-sm font-semibold text-bg"
            >
              Open the operator console →
            </Link>
          </div>
        </Reveal>

        {/* Static by design. This is what a sceptic came to read. */}
        <p className="mt-16 border-t border-line pt-6 text-[0.78rem] leading-relaxed text-mute">
          All data is simulated, deliberately: simulation is the only way to know ground truth well
          enough to score honestly. Thresholds were tuned on one set of scenarios (seeds 1000–1999)
          and scored once on another the system never saw (seeds 9000–9999). The false-alarm rate
          comes from three control runs, so its confidence interval is wide — 0.1 to 10.9 — and is
          reported rather than hidden.
        </p>
      </section>
    </>
  );
}
