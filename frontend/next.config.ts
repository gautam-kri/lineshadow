import type { NextConfig } from "next";

/**
 * Two build targets.
 *
 *   default        dev / local production. Talks to the FastAPI engine on :8000,
 *                  so every feature works including the live perturbation panel.
 *   STATIC_EXPORT  GitHub Pages. Emits a fully static site that reads JSON baked
 *                  by scripts/export_static_api.py. Pages cannot run Python, so
 *                  the perturbation panel is disabled rather than faked.
 *
 * BASE_PATH is required for a project Pages site, which is served from
 * /<repo> rather than the domain root.
 */
const isStaticExport = process.env.NEXT_PUBLIC_STATIC_API === "1";
const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

const nextConfig: NextConfig = {
  // Next regenerates AGENTS.md / CLAUDE.md on every dev run. This repo does not
  // ship editor or agent tooling config, so turn that off at the source.
  agentRules: false,

  ...(isStaticExport
    ? {
        output: "export" as const,
        basePath,
        // The export has no image optimiser behind it.
        images: { unoptimized: true },
        // Pages serves /path/ as /path/index.html.
        trailingSlash: true,
      }
    : {}),
};

export default nextConfig;
