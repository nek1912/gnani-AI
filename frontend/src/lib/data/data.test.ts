import { test, expect } from "vitest";
import { getSchemes, getScheme } from "./schemes";
import { getLibraryDocs } from "./library";
import { getGrievanceCategories, submitGrievance, getGrievanceStatus } from "./grievance";

test("schemes accessors return well-formed data", () => {
  const all = getSchemes("en");
  expect(all.length).toBeGreaterThan(0);
  expect(all[0]).toHaveProperty("slug");
  expect(getScheme("en", "pmfby")).toBeDefined();
  expect(getScheme("en", "does-not-exist")).toBeUndefined();
});

test("library accessor returns documents", () => {
  const docs = getLibraryDocs("en");
  expect(docs.length).toBeGreaterThan(0);
  expect(docs[0]).toHaveProperty("title");
  expect(docs[0]).toHaveProperty("url");
});

test("submitting a grievance produces a record with status 'submitted'", () => {
  const cats = getGrievanceCategories();
  expect(cats.length).toBeGreaterThan(0);
  const rec = submitGrievance({ categoryId: cats[0].id, details: "sector account closed" });
  expect(rec.id).toMatch(/^GRV-/);
  expect(rec.status).toBe("submitted");
  expect(rec.timeline[0].status).toBe("submitted");
  expect(getGrievanceStatus(rec.id)?.id).toBe(rec.id);
  expect(getGrievanceStatus("GRV-nope")).toBeUndefined();
});
