// The seeded users (ADR 0003: no real authentication).
export const USERS = [
  { id: "20000000-0000-4000-8000-00000000000a", name: "User A" },
  { id: "20000000-0000-4000-8000-00000000000b", name: "User B" },
];

export type Room = { id: string; name: string };

export type Booking = {
  id: string;
  room_id: string;
  user_id: string;
  start: string;
  end: string;
  status: "confirmed" | "cancelled";
};

export class ApiError extends Error {}

export async function request<T>(
  userId: string,
  path: string,
  options: { method?: string; body?: unknown; headers?: Record<string, string> } = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch("/api" + path, {
      method: options.method ?? "GET",
      headers: { "X-User-Id": userId, "Content-Type": "application/json", ...options.headers },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  } catch {
    throw new ApiError("Could not reach the server. Try again.");
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    if (body?.title) {
      throw new ApiError(body.detail ? `${body.title} ${body.detail}` : body.title);
    }
    throw new ApiError(`Request failed with status ${response.status}.`);
  }
  return body as T;
}

// The API returns UTC as "YYYY-MM-DDTHH:MM:SSZ". Slicing the string instead of using Date
// keeps the browser's time zone out of the picture.
export function formatUtc(iso: string): string {
  return `${iso.slice(0, 10)} ${iso.slice(11, 16)} UTC`;
}

// A datetime-local value ("YYYY-MM-DDTHH:MM") is read as UTC.
export function toUtcIso(local: string): string {
  return `${local}:00Z`;
}
