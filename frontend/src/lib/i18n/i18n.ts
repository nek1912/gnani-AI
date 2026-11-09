export const LOCALES = ["en", "hi", "gu", "mr", "bn", "ta", "te", "kn", "pa", "or", "ml"] as const;
export type Locale = (typeof LOCALES)[number];
