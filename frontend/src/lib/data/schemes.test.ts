import { test, expect } from "vitest";
import { getSchemes, getScheme } from "./schemes";

test("getSchemes returns localized data for a locale", () => {
  const all = getSchemes("en");
  expect(all.length).toBeGreaterThan(0);
  expect(all[0]).toHaveProperty("slug");
  expect(all[0].name).toBeTypeOf("string");
  expect(getScheme("en", "pmfby")).toBeDefined();
  expect(getSchemes("gu")[0].name).not.toBe(getSchemes("en")[0].name);
  expect(getScheme("en", "nope")).toBeUndefined();
});
