import { useEffect, useMemo, useState } from "react";
import type { Locale } from "@/lib/i18n/i18n";
import { createTranslator } from "./translator";

type RawEntry = Record<string, unknown>;

/**
 * Translates content fields that are missing a translation for `locale`
 * (i.e. they fell back to English) via Azure, then returns the translated copy.
 * Falls back to the original values when Azure is unavailable or a translation
 * already exists for the locale. Results are cached by the translator.
 *
 * The effect is keyed on a stable JSON signature of its inputs rather than on
 * the input references. Callers commonly pass fresh array/object literals every
 * render; depending on their identity would re-run the effect on each render
 * and hit "Maximum update depth exceeded". Two equal-content arrays produce the
 * same signature, so a re-render with identical data is a no-op, while a real
 * content change (e.g. switching slug or locale) re-runs the translation.
 */
export function useTranslatedFields<T>(opts: {
  locale: Locale;
  items: T[];
  rawItems: RawEntry[];
  textFields: string[];
  listFields: string[];
}): T[] {
  const { locale, items, rawItems, textFields, listFields } = opts;
  const [out, setOut] = useState<T[]>(items);

  const signature = useMemo(
    () => JSON.stringify([locale, items, rawItems, textFields, listFields]),
    [locale, items, rawItems, textFields, listFields],
  );

  useEffect(() => {
    let cancelled = false;

    async function run() {
      if (locale === "en") {
        setOut((prev) => (Object.is(prev, items) ? prev : items));
        return;
      }
      const t = createTranslator();
      const next = structuredClone(items) as T[];
      const flat: string[] = [];
      const mapping: { i: number; field: string; idx: number }[] = [];

      const entry = (i: number): Record<string, unknown> =>
        next[i] as unknown as Record<string, unknown>;
      const raw = (i: number): RawEntry => rawItems[i];

      for (let i = 0; i < items.length; i++) {
        const item = entry(i);
        const rawItem = raw(i);
        for (const f of textFields) {
          const localized = item[f];
          if (
            typeof localized === "string" &&
            (rawItem[f] as RawEntry | undefined)?.[locale] === undefined
          ) {
            flat.push(localized);
            mapping.push({ i, field: f, idx: -1 });
          }
        }
        for (const f of listFields) {
          const localized = item[f];
          const rawArr = (rawItem[f] as RawEntry | undefined)?.[locale];
          if (Array.isArray(localized) && rawArr === undefined) {
            const arr = localized as unknown[];
            arr.forEach((_v, idx) => {
              flat.push(arr[idx] as string);
              mapping.push({ i, field: f, idx });
            });
          }
        }
      }

      if (flat.length) {
        const resolved = await t.translateBatch(flat, locale);
        mapping.forEach((m, k) => {
          const v = resolved[k];
          const target = entry(m.i)[m.field];
          if (Array.isArray(target) && m.idx >= 0) {
            (target as unknown[])[m.idx] = v;
          } else {
            (entry(m.i) as Record<string, unknown>)[m.field] = v;
          }
        });
      }

      if (!cancelled) setOut((prev) => (Object.is(prev, next) ? prev : next));
    }

    run();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature]);

  return out;
}
