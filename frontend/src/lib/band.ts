export type Band = "strong" | "moderate" | "weak";
export function evidenceBand(confidence: number): Band {
  if (confidence >= 0.65) return "strong";
  if (confidence >= 0.45) return "moderate";
  return "weak";
}
export const BAND_LABEL: Record<Band, string> = {
  strong: "Strong source support",
  moderate: "Moderate source support",
  weak: "Weak source support",
};
