const encoder = new TextEncoder();

export const PRIVATE_SESSION_COOKIE = "__Host-company_facts_session";

function hex(bytes: ArrayBuffer): string {
  return Array.from(new Uint8Array(bytes), (value) => value.toString(16).padStart(2, "0")).join("");
}

async function signature(secret: string, payload: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return hex(await crypto.subtle.sign("HMAC", key, encoder.encode(payload)));
}

function equal(left: string, right: string): boolean {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) {
    difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return difference === 0;
}

export async function createPrivateSession(
  secret: string,
  now = Date.now(),
  lifetimeHours = 12,
): Promise<string> {
  const expiresAt = now + lifetimeHours * 60 * 60 * 1000;
  const payload = `v1.${expiresAt}`;
  return `${payload}.${await signature(secret, payload)}`;
}

export async function verifyPrivateSession(
  token: string | undefined,
  secret: string,
  now = Date.now(),
): Promise<boolean> {
  if (!token) return false;
  const parts = token.split(".");
  if (parts.length !== 3 || parts[0] !== "v1") return false;
  const expiresAt = Number(parts[1]);
  if (!Number.isSafeInteger(expiresAt) || expiresAt <= now) return false;
  const payload = `${parts[0]}.${parts[1]}`;
  return equal(parts[2], await signature(secret, payload));
}
