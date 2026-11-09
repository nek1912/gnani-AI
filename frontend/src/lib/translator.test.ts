import { test, expect, vi, afterEach } from "vitest";
import { createTranslator } from "./translator";

afterEach(() => {
  vi.unstubAllGlobals();
});

test("returns the original text when the API fails", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 503 }));
  const t = createTranslator();
  expect(await t.translate("hello", "hi")).toBe("hello");
});

test("translates and caches repeated calls", async () => {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      calls.push(init?.body as string);
      return {
        ok: true,
        status: 200,
        json: async () => ({ translations: ["नमस्ते"] }),
      } as Response;
    }),
  );
  const t = createTranslator();
  expect(await t.translate("hello", "hi")).toBe("नमस्ते");
  expect(await t.translate("hello", "hi")).toBe("नमस्ते");
  expect(calls.length).toBe(1);
});

test("batch returns originals on failure", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network")));
  const t = createTranslator();
  const out = await t.translateBatch(["a", "b"], "te");
  expect(out).toEqual(["a", "b"]);
});
