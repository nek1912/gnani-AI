import { test, expect } from "vitest";
import { getFaqItems } from "./faq";

test("faq items are well-formed", () => {
  const all = getFaqItems("en");
  expect(all.length).toBeGreaterThan(0);
  expect(all[0]).toHaveProperty("id");
  expect(all[0]).toHaveProperty("category");
  expect(all[0]).toHaveProperty("question");
  expect(all[0]).toHaveProperty("answer");
  expect(all[0].question).toBeTypeOf("string");
});
