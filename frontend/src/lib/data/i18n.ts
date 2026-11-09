import type { Locale } from "@/lib/i18n/i18n";

export type I18nText = Partial<Record<string, string>>;
export type I18nList = Partial<Record<string, string[]>>;

export function localize(value: I18nText, locale: Locale): string {
  return value[locale] ?? value.en ?? "";
}
export function localizeList(value: I18nList, locale: Locale): string[] {
  return value[locale] ?? value.en ?? [];
}
