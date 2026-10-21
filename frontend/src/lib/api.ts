import { t } from "./i18n";const API_BASE = import.meta.env.VITE_API_BASE_URL as string | undefined ?? import.meta.env.BASE_URL.replace(/\/$/, "");

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function detailMessage(detail: unknown): string {
  if (typeof detail === "string") return t(detail);
  if (Array.isArray(detail)) {
    return detail.
    map((item) => typeof item === "object" && item && "msg" in item ? String(item.msg) : String(item)).
    join(t("؛ "));
  }
  if (detail && typeof detail === "object" && "message" in detail) {
    return String(detail.message);
  }
  return t("درخواست با خطا مواجه شد.");
}

async function request<T>(path: string, options: RequestInit = {}, responseType?: "blob"): Promise<T> {
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE}${path}`, { ...options, headers, credentials: "include" });
  if (!response.ok) {
    let detail: unknown = null;
    try {
      const data = await response.json();
      detail = data.detail ?? data;
    } catch {
      detail = response.statusText;
    }
    if (response.status === 401 && !path.includes("/auth/session")) {
      window.dispatchEvent(new Event("spectergate:unauthorized"));
    }
    throw new ApiError(detailMessage(detail), response.status);
  }
  if (response.status === 204) return undefined as T;
  if (responseType === "blob") return (await response.blob()) as T;
  return (await response.json()) as T;
}

export const api = {
  upload: <T,>(path: string, body: FormData) => request<T>(path, { method: "POST", body }),
  download: (path: string, body?: unknown) => request<Blob>(path, { method: "POST", body: JSON.stringify(body ?? {}) }, "blob"),
  get: <T,>(path: string) => request<T>(path),
  post: <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  put: <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: "PUT", body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: "PATCH", body: body === undefined ? undefined : JSON.stringify(body) }),
  delete: <T,>(path: string) => request<T>(path, { method: "DELETE" })
};

export { API_BASE };
