import { useMemo } from "react";
import { useI18n } from "@/lib/i18n/provider";
import { createTranslator } from "./translator";

/**
 * Translation helpers bound to the active UI locale.
 * `translate` / `translateBatch` call the server proxy (/api/translate) and cache
 * results; on any failure they return the original text (safe English fallback).
 */
export function useTranslate() {
  const { locale } = useI18n();
  const t = useMemo(() => createTranslator(), []);
  return {
    locale,
    translate: (text: string, to: string = locale) => t.translate(text, to),
    translateBatch: (texts: string[], to: string = locale) => t.translateBatch(texts, to),
  };
}
