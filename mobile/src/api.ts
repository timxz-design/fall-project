/**
 * Backend API client.
 *
 * Endpoints matching backend/app.py:
 *   POST /register-device       — link an FCM/Expo token to a home
 *   GET  /events?home_id=X      — fetch event history
 *   POST /events/{id}/label     — label an event
 *   GET  /status                — health snapshot
 */
import Constants from "expo-constants";

const BASE_URL: string =
  (Constants.expoConfig?.extra?.backendUrl as string) ??
  "http://localhost:8000";

export type Platform = "ios" | "android";
export type LabelValue = "real_fall" | "false_alarm" | "test" | "unsure";

export interface EventSummary {
  id: number;
  event_type: string;
  detected_at: string;
  confidence: number | null;
  label: LabelValue | null;
  label_source: string | null;
  labeled_at: string | null;
  note: string | null;
}

export interface RegisterResponse {
  home_id: number;
  owner_name: string;
}

async function jsonFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`HTTP ${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export async function registerDevice(
  installCode: string,
  pushToken: string,
  platform: Platform
): Promise<RegisterResponse> {
  return jsonFetch<RegisterResponse>("/register-device", {
    method: "POST",
    body: JSON.stringify({
      install_code: installCode,
      fcm_token: pushToken,
      platform,
    }),
  });
}

export async function getEvents(
  homeId: number,
  limit = 50
): Promise<EventSummary[]> {
  return jsonFetch<EventSummary[]>(`/events?home_id=${homeId}&limit=${limit}`);
}

export async function labelEvent(
  eventId: number,
  label: LabelValue,
  note?: string
): Promise<{ ok: boolean }> {
  return jsonFetch(`/events/${eventId}/label`, {
    method: "POST",
    body: JSON.stringify({ label, note: note ?? null, label_source: "user" }),
  });
}

export async function getStatus(): Promise<unknown> {
  return jsonFetch("/status");
}

export const __baseUrl = BASE_URL; // exported for the settings/debug screen
