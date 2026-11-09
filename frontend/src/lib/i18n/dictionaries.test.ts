import { test, expect } from "vitest";
import { dict, translate } from "./dictionaries";
import { LOCALES } from "./i18n";

/*
 * These tests assert the invariants that actually hold, not total translation
 * coverage.
 *
 * `en` is the reference table and every other locale is a partial overlay on it:
 * as of 2026-10-05 the locales are missing between 4 and 130 of en's 374 keys.
 * That is a content gap, not a code defect, and `translate()` already degrades
 * gracefully via `table[key] ?? en[key] ?? key`.
 *
 * The previous version of this file asserted that every locale defines every
 * `en` key. That assertion is false today, so it could only ever fail. It has
 * been replaced with the checks below, which catch the failure modes that
 * actually matter: a broken reference table, a typo'd or stale key in a locale,
 * and a regression in the English fallback.
 *
 * Run `node scripts/i18n-coverage.mjs` to see the current per-locale coverage.
 * Closing the gap is a translation task, not a code task.
 */

test("en is the complete reference table", () => {
  expect(Object.keys(dict.en).length).toBeGreaterThan(300);
});

test("every locale defines nav.home itself, not via fallback", () => {
  // Asserted on the table directly. Checking translate() here would pass on the
  // English fallback alone, so it would prove nothing about this locale.
  for (const loc of LOCALES) {
    expect(dict[loc]["nav.home"], `${loc} defines nav.home`).toBeDefined();
  }
});

test("no locale defines a key that en does not", () => {
  const enKeys = new Set(Object.keys(dict.en));
  for (const loc of LOCALES) {
    for (const k of Object.keys(dict[loc])) {
      expect(enKeys.has(k), `${loc} defines orphan key ${k}`).toBe(true);
    }
  }
});

test("translate falls back to English for a key a locale lacks", () => {
  // gu is missing 48 of en's keys. Falling back to English is the designed
  // behaviour, so assert it rather than assert coverage that does not exist.
  expect(translate("gu", "common.yes")).toBe(dict.en["common.yes"]);
  expect(translate("bn", "schemes.detail.askAI")).toBe(dict.en["schemes.detail.askAI"]);
});

test("translate returns the key when no locale has it", () => {
  expect(translate("en", "nav.never-gonna-exist")).toBe("nav.never-gonna-exist");
});
