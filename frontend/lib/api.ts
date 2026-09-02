import type {
  HoldoutBundle,
  LineModel,
  PerturbationRequest,
  RunPayload,
  ScenarioSummary,
} from "./types";

/**
 * Client for the engine.
 *
 * Two modes, same interface:
 *
 *   live    talks to the FastAPI wrapper in `api/main.py`. Everything works,
 *           including the live perturbation panel.
 *   static  reads JSON baked by `scripts/export_static_api.py`. This is what the
 *           GitHub Pages build uses, because Pages serves static files and cannot
 *           run the Python engine.
 *
 * In both modes every number is something the engine computed. Nothing is
 * derived, rounded or reinterpreted on this side -- if a figure needs to change,
 * it changes in the engine.
 */

const STATIC = process.env.NEXT_PUBLIC_STATIC_API === "1";
const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
const LIVE_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

/** True when running against baked data, so the UI can say what it cannot do. */
export const isStatic = STATIC;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    /** Set when the operation is impossible in this mode, not merely failing. */
    readonly unsupported = false,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, { signal, cache: "no-store" });
  } catch (cause) {
    if (signal?.aborted) throw cause;
    throw new ApiError(
      STATIC
        ? `Could not load ${url}.`
        : `Cannot reach the engine at ${LIVE_BASE}. Start it with: uvicorn api.main:app --port 8000`,
      0,
    );
  }
  if (!response.ok) throw new ApiError(await describe(response), response.status);
  return (await response.json()) as T;
}

async function describe(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
    return JSON.stringify(body?.detail ?? body);
  } catch {
    return `${response.status} ${response.statusText}`;
  }
}

const staticUrl = (path: string) => `${BASE_PATH}/api/${path}`;

/** The twelve sweep sensitivities the static build is baked at. */
let sensitivityPoints: number[] | null = null;

async function nearestIndex(sensitivity: number, signal?: AbortSignal): Promise<number> {
  if (!sensitivityPoints) {
    sensitivityPoints = await getJson<number[]>(staticUrl("sensitivities.json"), signal);
  }
  let best = 0;
  let bestGap = Infinity;
  sensitivityPoints.forEach((point, index) => {
    const gap = Math.abs(point - sensitivity);
    if (gap < bestGap) {
      bestGap = gap;
      best = index;
    }
  });
  return best;
}

export const api = {
  line: (signal?: AbortSignal) =>
    getJson<LineModel>(STATIC ? staticUrl("line.json") : `${LIVE_BASE}/api/line`, signal),

  scenarios: (signal?: AbortSignal) =>
    getJson<ScenarioSummary[]>(
      STATIC ? staticUrl("scenarios.json") : `${LIVE_BASE}/api/scenarios`,
      signal,
    ),

  holdout: (signal?: AbortSignal) =>
    getJson<HoldoutBundle>(STATIC ? staticUrl("holdout.json") : `${LIVE_BASE}/api/holdout`, signal),

  /**
   * Twin state and alerts at a given sensitivity.
   *
   * Static mode snaps to the nearest of the twelve measured sweep points rather
   * than interpolating, so every slider position corresponds to a scored run.
   */
  async run(scenarioId: string, sensitivity: number, signal?: AbortSignal): Promise<RunPayload> {
    if (!STATIC) {
      return getJson<RunPayload>(
        `${LIVE_BASE}/api/run/${encodeURIComponent(scenarioId)}?sensitivity=${sensitivity.toFixed(2)}`,
        signal,
      );
    }
    const index = await nearestIndex(sensitivity, signal);
    return getJson<RunPayload>(
      staticUrl(`run/${encodeURIComponent(scenarioId)}/${index}.json`),
      signal,
    );
  },

  /**
   * Genuinely re-runs simulate -> same-seed counterfactual -> twin -> score.
   *
   * Impossible on a static host, and deliberately not faked: replaying a canned
   * result would undo the single claim this panel exists to make.
   */
  async perturb(request: PerturbationRequest, signal?: AbortSignal): Promise<RunPayload> {
    if (STATIC) {
      throw new ApiError(
        "The live perturbation panel runs a new simulation and its counterfactual " +
          "server-side, so it needs the Python engine. It is not replayed here. " +
          "Run the project locally to use it.",
        501,
        true,
      );
    }
    let response: Response;
    try {
      response = await fetch(`${LIVE_BASE}/api/perturb`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
        signal,
      });
    } catch (cause) {
      if (signal?.aborted) throw cause;
      throw new ApiError(`Cannot reach the engine at ${LIVE_BASE}.`, 0);
    }
    if (!response.ok) throw new ApiError(await describe(response), response.status);
    return (await response.json()) as RunPayload;
  },
};
