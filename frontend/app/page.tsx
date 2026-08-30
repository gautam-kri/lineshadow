import Link from "next/link";

/**
 * Zone A placeholder.
 *
 * The scroll-told narrative shell belongs here: hero, the problem, the
 * counterfactual explainer, the three layers, the sparse-sensor differentiator,
 * and the CTA into the console. It is not built yet because it is the one part
 * of this app that is mostly motion, and the motion skills that govern it could
 * not be loaded in the session that built Zone B.
 *
 * Zone B (/console) is complete and is what the live demo runs against.
 */
export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-3xl flex-col justify-center px-6 py-20">
      <div className="flex items-baseline gap-2.5">
        <span className="text-2xl text-accent">◧</span>
        <h1 className="font-display text-3xl font-semibold tracking-tight">Ninja</h1>
      </div>

      <p className="font-display mt-6 text-2xl leading-snug tracking-tight text-fg sm:text-3xl">
        A digital twin that sees the bottleneck{" "}
        <span className="text-accent">37 minutes</span> before the line backs up.
      </p>

      <p className="mt-5 max-w-xl text-sm leading-relaxed text-dim">
        A 40-station mixed-model vehicle assembly line. Only 26 of the 40 stations have sensors —
        the rest emit nothing per unit, and buffer levels are never reported anywhere. Ninja reads
        the event stream, infers what it cannot see, and calls it early.
      </p>

      <dl className="mt-8 grid grid-cols-2 gap-6 sm:grid-cols-4">
        {[
          ["+37 min", "median lead time"],
          ["99.2%", "defect containment"],
          ["6 / 6", "faults detected"],
          ["5.5", "false alarms / shift"],
        ].map(([value, label]) => (
          <div key={label}>
            <dt className="font-display tnum text-2xl font-semibold tracking-tight text-fg">
              {value}
            </dt>
            <dd className="mt-1 text-[0.72rem] leading-tight text-mute">{label}</dd>
          </div>
        ))}
      </dl>

      <p className="mt-6 text-[0.75rem] text-mute">
        All figures from sealed holdout scenarios, scored against a frozen config.
      </p>

      <div className="mt-10">
        <Link
          href="/console"
          className="inline-block rounded-lg bg-accent px-5 py-2.5 text-sm font-semibold text-bg"
        >
          Open the operator console →
        </Link>
      </div>

      <p className="mt-12 border-t border-line pt-4 text-[0.72rem] leading-relaxed text-mute">
        The scroll-told narrative shell (Zone A) is not built yet. This page is a static stand-in;
        the working console at <code className="font-mono text-dim">/console</code> is complete.
      </p>
    </main>
  );
}
