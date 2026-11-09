const ACCENTS = ["#047857", "#b45309", "#1d4ed8", "#6d28d9", "#be123c"];
export function slugAccent(slug: string): string {
  let h = 0;
  for (let i = 0; i < slug.length; i++) h = (h * 31 + slug.charCodeAt(i)) >>> 0;
  return ACCENTS[h % ACCENTS.length];
}
