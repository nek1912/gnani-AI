export const DECO = {
  teal: "#4e99a3",
  blue: "#5691c7",
  green: "#539e55",
  gold: "#bc811e",
  indigo: "#7989e7",
  lime: "#859531",
  magenta: "#d163a7",
  orange: "#d57141",
  pink: "#dc6973",
  purple: "#a96ee0",
} as const;

const PALETTE = Object.values(DECO);

const CATEGORY_DECO: Record<string, string> = {
  // schemes
  "crop-insurance": DECO.gold,
  pacs: DECO.teal,
  financial: DECO.blue,
  subsidy: DECO.green,
  // services
  credit: DECO.blue,
  storage: DECO.orange,
  insurance: DECO.gold,
  "agro-inputs": DECO.lime,
  membership: DECO.purple,
  // legal
  act: DECO.indigo,
  "bye-laws": DECO.magenta,
  provisions: DECO.gold,
  // library domains
  cropInsurance: DECO.gold,
  law: DECO.indigo,
  grievance: DECO.orange,
};

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h;
}

export function deco(key: string): string {
  const resolved = CATEGORY_DECO[key];
  if (resolved) return resolved;
  return PALETTE[hash(key) % PALETTE.length];
}

export function decoTint(key: string): string {
  return `${deco(key)}29`;
}

// Domain-aware accent colors for editorial card styling
// Maps category → institutional accent color
export const DOMAIN_ACCENTS: Record<string, { accent: string; label: string }> = {
  // Schemes
  "crop-insurance": { accent: "#526B58", label: "Agriculture" },
  pacs: { accent: "#C65D2E", label: "Cooperative" },
  financial: { accent: "#27364A", label: "Financial" },
  subsidy: { accent: "#526B58", label: "Agriculture" },
  // Services
  credit: { accent: "#27364A", label: "Financial" },
  storage: { accent: "#526B58", label: "Agriculture" },
  insurance: { accent: "#27364A", label: "Financial" },
  "agro-inputs": { accent: "#526B58", label: "Agriculture" },
  membership: { accent: "#C65D2E", label: "Cooperative" },
  // Legal
  act: { accent: "#27364A", label: "Legal" },
  "bye-laws": { accent: "#27364A", label: "Legal" },
  provisions: { accent: "#27364A", label: "Legal" },
};

export function domainAccent(category: string): string {
  return DOMAIN_ACCENTS[category]?.accent ?? "#6F706A";
}

export function domainLabel(category: string): string {
  return DOMAIN_ACCENTS[category]?.label ?? "Information";
}
