import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Next regenerates AGENTS.md / CLAUDE.md on every dev run. This repo does not
  // ship editor or agent tooling config, so turn that off at the source rather
  // than deleting the files repeatedly.
  agentRules: false,
};

export default nextConfig;
