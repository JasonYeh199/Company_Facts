import { describe, expect, it } from "vitest";

import { createPrivateSession, verifyPrivateSession } from "./private-auth";

describe("private session", () => {
  it("accepts a signed unexpired token and rejects tampering or expiry", async () => {
    const token = await createPrivateSession("a-secret-at-least-32-characters-long", 1_000, 1);
    expect(await verifyPrivateSession(token, "a-secret-at-least-32-characters-long", 2_000)).toBe(true);
    expect(await verifyPrivateSession(`${token}x`, "a-secret-at-least-32-characters-long", 2_000)).toBe(false);
    expect(await verifyPrivateSession(token, "a-secret-at-least-32-characters-long", 3_601_001)).toBe(false);
  });
});
