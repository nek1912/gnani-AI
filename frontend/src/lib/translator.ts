
import { apiFetch } from "./backend";

const cache = new Map<string, string>();

function key(to: string, text: string): string {
  return `${to}\u0001${text}`;
}

export interface Translator {
  translate: (text: string, to: string) => Promise<string>;
  translateBatch: (texts: string[], to: string) => Promise<string[]>;
}

/**
 * Client-side translator. Calls the FastAPI backend directly and caches
 * results in memory. On any failure, returns the
 * original text so the UI still renders (English fallback).
 */
export function createTranslator(): Translator {
  async function call(texts: string[], to: string): Promise<string[]> {
    const res = await apiFetch("/api/translate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // FastAPI names this field `target_language`. While requests went through
      // the BFF the payload sent `to`, which the backend discarded, so the
      // target silently fell back to "hi" for every user.
      body: JSON.stringify({ texts, target_language: to }),
    });
    if (!res.ok) throw new Error(`translate ${res.status}`);
    const data = (await res.json()) as { translations: string[] };
    return data.translations;
  }

  async function lookup(text: string, to: string): Promise<string> {
    const k = key(to, text);
    const hit = cache.get(k);
    if (hit !== undefined) return hit;
    try {
      const [translated] = await call([text], to);
      const out = translated || text;
      cache.set(k, out);
      return out;
    } catch {
      return text;
    }
  }

  async function batch(texts: string[], to: string): Promise<string[]> {
    const missing: number[] = [];
    const out = new Array<string>(texts.length);
    texts.forEach((t, i) => {
      const hit = cache.get(key(to, t));
      if (hit !== undefined) out[i] = hit;
      else missing.push(i);
    });
    if (missing.length) {
      try {
        const translated = await call(missing.map((i) => texts[i]), to);
        missing.forEach((i, k) => {
          const v = translated[k] || texts[i];
          out[i] = v;
          cache.set(key(to, texts[i]), v);
        });
      } catch {
        missing.forEach((i) => {
          out[i] = texts[i];
        });
      }
    }
    return out;
  }

  return { translate: lookup, translateBatch: batch };
}
