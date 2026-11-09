import { test, expect } from "vitest";
import { getServices, getService } from "./services";

test("services accessors return well-formed data", () => {
  const all = getServices("en");
  expect(all.length).toBeGreaterThan(0);
  expect(all[0]).toHaveProperty("slug");
  expect(all[0]).toHaveProperty("category");
  expect(all[0].name).toBeTypeOf("string");
  const slugs = new Set(all.map((s) => s.slug));
  expect(slugs.size).toBe(all.length);
  expect(getService("en", "pacs-membership")).toBeDefined();
  expect(getService("en", "pacs-membership")?.name).toBeTypeOf("string");
  expect(getService("en", "nope")).toBeUndefined();
});
