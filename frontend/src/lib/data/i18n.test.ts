import { test, expect } from "vitest";
import { localize, localizeList, type I18nText, type I18nList } from "./i18n";

test("localize returns the requested locale", () => {
  const v: I18nText = { en: "Apple", hi: "सेब" };
  expect(localize(v, "hi")).toBe("सेब");
});

test("localize falls back to en when locale missing", () => {
  const v: I18nText = { en: "Apple" };
  expect(localize(v, "gu")).toBe("Apple");
});

test("localizeList returns requested locale array", () => {
  const v: I18nList = { en: ["a"], hi: ["ख"] };
  expect(localizeList(v, "hi")).toEqual(["ख"]);
});

test("localizeList falls back to en when locale missing", () => {
  const v: I18nList = { en: ["a"] };
  expect(localizeList(v, "gu")).toEqual(["a"]);
});
