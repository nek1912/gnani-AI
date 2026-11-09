/*
 * Reports per-locale translation coverage against the English reference table.
 *
 * The dictionary test suite asserts the invariants that hold (no orphan keys,
 * working English fallback) rather than total coverage, because coverage is
 * incomplete by design at present. This script makes the gap measurable so it
 * stays visible instead of being silently forgotten.
 *
 * Run:  node scripts/i18n-coverage.mjs
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const dictPath = path.join(here, "..", "src", "lib", "i18n", "dictionaries.ts");
const src = readFileSync(dictPath, "utf8");

const LOCALES = ["en", "hi", "gu", "mr", "bn", "ta", "te", "kn", "pa", "or", "ml"];

const keysOf = (loc) => {
  const start = src.indexOf(`const ${loc}: Record<string, string> = {`);
  if (start < 0) return null;
  const end = src.indexOf("\n};", start);
  const body = src.slice(start, end);
  return new Set([...body.matchAll(/"([^"]+)":/g)].map((m) => m[1]));
};

const en = keysOf("en");
console.log(`English reference table: ${en.size} keys\n`);

let totalMissing = 0;
const rows = [];

for (const loc of LOCALES.slice(1)) {
  const set = keysOf(loc);
  // Fail loudly rather than silently dropping a locale from the totals.
  if (!set) {
    console.error(
      `\nERROR: could not locate \`const ${loc}\` in dictionaries.ts. ` +
        `Its coverage is EXCLUDED from the totals below, which would flatter the result.`,
    );
    process.exitCode = 1;
    continue;
  }
  const missing = [...en].filter((k) => !set.has(k));
  totalMissing += missing.length;
  const pct = ((set.size / en.size) * 100).toFixed(1);
  rows.push({ loc, have: set.size, missing: missing.length, pct });
}

for (const r of rows) {
  const bar = "#".repeat(Math.round(Number(r.pct) / 5)).padEnd(20, ".");
  console.log(
    `${r.loc}  ${String(r.have).padStart(3)}/${en.size}  ${r.pct.padStart(5)}%  ${bar}  ${r.missing} missing`,
  );
}

const totalSlots = rows.length * en.size;
console.log(
  `\nTOTAL missing strings: ${totalMissing} of ${totalSlots} ` +
    `(${((totalSlots - totalMissing) / totalSlots * 100).toFixed(1)}% overall coverage)`,
);
console.log(
  "\nUntranslated strings fall back to English via translate()'s `en[key]` lookup.",
);
