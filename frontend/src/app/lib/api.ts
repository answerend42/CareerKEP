import type {
  ActionSimulationResponse,
  CatalogResponse,
  RecommendationResponse,
  RoleGapResponse,
} from "../types/api";

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/+$/, "");

function apiUrl(path: string): string {
  return `${apiBaseUrl}${path}`;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(apiUrl(path), {
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
      ...init,
    });
  } catch (error) {
    throw new Error(error instanceof Error ? `无法连接后端服务：${error.message}` : "无法连接后端服务");
  }

  const rawPayload = await response.text();
  let payload: { error?: string } = {};
  try {
    payload = rawPayload ? (JSON.parse(rawPayload) as { error?: string }) : {};
  } catch {
    payload = {};
  }
  if (!response.ok) {
    throw new Error(payload.error || `request failed: ${response.status}`);
  }
  return payload as T;
}

export const api = {
  catalog(): Promise<CatalogResponse> {
    return requestJson<CatalogResponse>("/api/catalog");
  },
  recommend(payload: unknown): Promise<RecommendationResponse> {
    return requestJson<RecommendationResponse>("/api/recommend", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  roleGap(payload: unknown): Promise<RoleGapResponse> {
    return requestJson<RoleGapResponse>("/api/role-gap", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  actionSimulate(payload: unknown): Promise<ActionSimulationResponse> {
    return requestJson<ActionSimulationResponse>("/api/action-simulate", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
};
