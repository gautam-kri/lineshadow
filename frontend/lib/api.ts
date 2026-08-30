import type {
  HoldoutBundle,
  LineModel,
  PerturbationRequest,
  RunPayload,
  ScenarioSummary,
} from "./types";

/**
 * Client for the FastAPI wrapper in `api/main.py`.
 *
 * Everything here is a read of the Python engine's own output. No metric is
 * derived, rounded or reinterpreted on this side -- if a number needs to change,
 * it changes in the engine.
 */
const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, { signal, cache: "no-store" });
  } catch (cause) {
    if (signal?.aborted) throw cause;
    throw new ApiError(
      `Cannot reach the engine at ${BASE}. Start it with: uvicorn api.main:app --port 8000`,
      0,
    );
  }
  if (!response.ok) {
    throw new ApiError(await describe(response), response.status);
  }
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

export const api = {
  line: (signal?: AbortSignal) => get<LineModel>("/api/line", signal),

  scenarios: (signal?: AbortSignal) => get<ScenarioSummary[]>("/api/scenarios", signal),

  run: (scenarioId: string, sensitivity: number, signal?: AbortSignal) =>
    get<RunPayload>(
      `/api/run/${encodeURIComponent(scenarioId)}?sensitivity=${sensitivity.toFixed(2)}`,
      signal,
    ),

  holdout: (signal?: AbortSignal) => get<HoldoutBundle>("/api/holdout", signal),

  /**
   * Genuinely re-runs simulate -> same-seed counterfactual -> twin -> score.
   * Takes 1-3 seconds server side; never render a result before it resolves.
   */
  async perturb(request: PerturbationRequest, signal?: AbortSignal): Promise<RunPayload> {
    let response: Response;
    try {
      response = await fetch(`${BASE}/api/perturb`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
        signal,
      });
    } catch (cause) {
      if (signal?.aborted) throw cause;
      throw new ApiError(`Cannot reach the engine at ${BASE}.`, 0);
    }
    if (!response.ok) throw new ApiError(await describe(response), response.status);
    return (await response.json()) as RunPayload;
  },
};
