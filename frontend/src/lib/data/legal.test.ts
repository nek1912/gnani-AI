import { test, expect } from "vitest";
import { getLegalDocs, getLegalDoc } from "./legal";

test("legal accessors return well-formed data", () => {
  const all = getLegalDocs("en");
  expect(all.length).toBeGreaterThan(0);
  expect(all[0]).toHaveProperty("slug");
  expect(all[0]).toHaveProperty("category");
  expect(getLegalDocs("en")[0].title).toBeTypeOf("string");
  const slugs = new Set(all.map((d) => d.slug));
  expect(slugs.size).toBe(all.length);
  expect(getLegalDoc("en", "mscs-act-2002")).toBeDefined();
  expect(getLegalDoc("en", "nope")).toBeUndefined();
});
