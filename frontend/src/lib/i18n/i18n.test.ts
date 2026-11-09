import { test, expect } from "vitest";
import { LOCALES } from "./i18n";
import { translate } from "./dictionaries";

test("exports supported locales", () => {
  expect(LOCALES).toEqual(["en", "hi", "gu", "mr", "bn", "ta", "te", "kn", "pa", "or", "ml"]);
});

test("translates known keys for en and hi", () => {
  expect(translate("en", "nav.home")).toBe("Home");
  expect(translate("hi", "nav.home")).toBe("होम");
});

test("falls back to English for unknown or missing locales", () => {
  expect(translate("zz", "nav.home")).toBe("Home");
  expect(translate("en", "nav.never-gonna-exist")).toBe("nav.never-gonna-exist");
});

test("interpolates {vars} in strings", () => {
  expect(translate("en", "schemes.count", { n: 3 })).toBe("3 schemes available");
});

test("root layout example translations resolve", () => {
  expect(translate("en", "landing.ctaChat")).toBe("Ask JanSahay →");
  expect(translate("hi", "evidence.strong")).toBe("प्रबल स्रोत समर्थन");
});
