import type { Locale } from "@/lib/i18n/i18n";
import { apiFetch } from "@/lib/backend";

export interface SpeechSegment {
  text: string;
  language: string;
}

export interface GrievanceLocation {
  ward_number: string | null;
  locality: string | null;
  area: string | null;
  city: string | null;
  district: string | null;
  state: string | null;
}

export interface GrievanceSubmission {
  portal_name: string | null;
  portal_url: string | null;
  department: string | null;
  level: string | null;
  steps: string[];
  required_documents: string[];
  estimated_timeline: string | null;
  disclaimer: string | null;
}

export interface GrievanceDescription {
  /** Exact, untouched citizen input — never edited or overwritten. */
  original: string;
  /** Canonical English description used by the workflow and for submission. */
  normalized: string;
  /** User-facing description, localized to the user's preferred language.
   *  Falls back to `normalized` (English) when no localization is available. */
  display: string;
}

export interface Grievance {
  reference: string | null;
  category: string;
  sub_category: string;
  department: string;
  jurisdiction: string;
  title: string;
  description: GrievanceDescription;
  /** Structured field key/value pairs (e.g. farmer_name, application_id)
   *  collected during the field wizard.  Preserves exact user-entered
   *  values — never rewritten or normalized. */
  fields: Record<string, string> | null;
  location: GrievanceLocation;
  submission: GrievanceSubmission | null;
  /** Full English-language mirror of the grievance, attached only when the
   *  user's selected language is non-English. Contains the complete canonical
   *  English representation (classification, description, location, submission
   *  steps, documents, timeline, disclaimer) so the frontend can render a
   *  full-page English preview without any translation. */
  english?: {
    category: string;
    sub_category: string;
    department: string;
    jurisdiction: string;
    title: string;
    description: string;
    fields: Record<string, string> | null;
    location: GrievanceLocation;
    submission: GrievanceSubmission | null;
  } | null;
}

export interface ChatResponse {
  answer: string;
  language: Locale;
  domain: string;
  intent: string;
  entities: string[];
  confidence: number;
  confidence_level: "high" | "moderate" | "low" | "none";
  citations: {
    chunk_id: string | null;
    document_id?: string | null;
    source_file?: string;
    title: string;
    page?: number;
    page_start?: number | null;
    page_end?: number | null;
    section?: string;
    subsection?: string;
    clause?: string;
    url: string;
    source?: "static" | "web";
    source_label?: string;
    content?: string;
  }[];
  abstained: boolean;
  /**
   * Frontend-only marker: the request never produced a backend answer (network
   * failure, non-2xx, aborted parse). Distinct from a backend abstention, which
   * means the pipeline ran and deliberately declined to answer. Without this the
   * error path reused the abstention card, so a 401 looked identical to a
   * grounding refusal.
   */
  transport_error?: boolean;
  mode?: string;
  grievance?: Grievance | null;
  grievance_stage?: "classification" | "fields" | "complete" | null;
  grievance_draft_summary?: {
    category: string;
    sub_category: string;
    jurisdiction: string;
    title: string;
    description: string;
    department: string;
  } | null;
  grievance_fields_schema?: {
    mandatory_fields: GrievanceFieldSpec[];
    optional_fields: GrievanceFieldSpec[];
  } | null;
  grievance_finalized?: boolean;
  conversation_id?: string;
  speech_text?: string;
  speech_segments?: SpeechSegment[];
  follow_up_question: string | null;
}

export interface GrievanceFieldSpec {
  field: string;
  field_label: string;
  question: string;
  input_type: "int" | "date" | "text";
  mandatory: boolean;
  value: string | null;
}

export interface GrievanceDetectResponse {
  status: string;
  response: string;
  stage: string;
  draft: {
    category: string;
    sub_category: string;
    title: string;
    description: string;
    jurisdiction: string;
    department: string;
    required_fields: string[];
    optional_fields: string[];
  } | null;
  is_complete: boolean;
  submission_route: unknown;
  evidence: unknown[];
}

export async function detectGrievance(payload: {
  message: string;
  conversation_id: string;
  user_id: string;
}): Promise<GrievanceDetectResponse> {
  const r = await apiFetch("/api/grievance/detect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(`API ${r.status}`);
  return r.json();
}

export async function getGrievanceFields(
  conversationId: string,
  language: string,
): Promise<{ status: string; mandatory_fields: GrievanceFieldSpec[]; optional_fields: GrievanceFieldSpec[] }> {
  const r = await apiFetch(
    `/api/grievance/fields?conversation_id=${encodeURIComponent(conversationId)}&language=${encodeURIComponent(language)}`,
  );
  if (!r.ok) throw new Error(`API ${r.status}`);
  return r.json();
}

export async function answerGrievanceField(payload: {
  conversation_id: string;
  field: string;
  value: string;
}): Promise<{ status: string }> {
  const r = await apiFetch("/api/grievance/answer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(`API ${r.status}`);
  return r.json();
}

export async function finalizeGrievanceDraft(payload: {
  conversation_id: string;
  language: string;
}): Promise<{ status: string; grievance: Grievance; mixed_language: boolean; speech_text?: string; speech_segments?: SpeechSegment[] }> {
  const r = await apiFetch("/api/grievance/finalize", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(`API ${r.status}`);
  return r.json();
}

export async function clarifyGrievance(payload: {
  conversation_id: string;
  complaint: string;
  language: string;
}): Promise<{
  status: string;
  stage: string;
  draft_summary: ChatResponse["grievance_draft_summary"];
  fields_schema: ChatResponse["grievance_fields_schema"];
}> {
  const r = await apiFetch("/api/grievance/clarify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(`API ${r.status}`);
  return r.json();
}

export async function sendChat(payload: {
  question: string;
  session_id: string;
  language: Locale;
  state: string | null;
  history?: Array<{ role: "user" | "assistant"; content: string }>;
  ui_language_explicit?: boolean;
  mode?: "static" | "web" | "rag_web";
}): Promise<ChatResponse> {
  const r = await apiFetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(`API ${r.status}`);
  return r.json();
}

export interface StepEvent {
  id: string;
  label: string;
  detail: string;
  status: "active" | "completed" | "pending";
}

export type StreamEvent =
  | { event: "thinking"; data: { text: string } }
  | { event: "step"; data: StepEvent }
  | { event: "token"; data: { text: string } }
  | { event: "metadata"; data: Record<string, unknown> }
  | { event: "done"; data: Record<string, unknown> }
  | { event: "error"; data: { message: string } };

export async function sendChatStream(
  payload: {
    question: string;
    session_id: string;
    language: Locale;
    state: string | null;
    history?: Array<{ role: "user" | "assistant"; content: string }>;
    ui_language_explicit?: boolean;
    mode?: "static" | "web" | "rag_web";
  },
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const r = await apiFetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  if (!r.ok) throw new Error(`API ${r.status}`);
  const reader = r.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    let currentEvent = "";
    for (const line of lines) {
      if (line.startsWith("event: ")) {
        currentEvent = line.slice(7).trim();
      } else if (line.startsWith("data: ")) {
        const raw = line.slice(6);
        try {
          const data = JSON.parse(raw);
          onEvent({ event: currentEvent as StreamEvent["event"], data } as StreamEvent);
        } catch {
          onEvent({ event: currentEvent as StreamEvent["event"], data: { text: raw } } as StreamEvent);
        }
        currentEvent = "";
      }
    }
  }
}

export interface TranslateItem {
  original: string;
  translated: string;
}

export async function translateTexts(
  texts: string[],
  sourceLanguage: string,
  targetLanguage: string,
): Promise<TranslateItem[]> {
  const r = await apiFetch("/api/translate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      texts,
      source_language: sourceLanguage,
      target_language: targetLanguage,
    }),
  });
  if (!r.ok) throw new Error(`Translate API ${r.status}`);
  const data = await r.json();
  return data.translations;
}

export interface VoiceTranscribeResponse {
  text: string;
  language: string;
  requested_language?: string;
  detected_language?: string | null;
  provider?: string;
  model?: string | null;
  duration_ms?: number;
  fallback_occurred?: boolean;
}

export interface VoiceSpeakResponse {
  audio: string;
  audio_base64?: string;
  language: string;
  provider?: string;
  model?: string | null;
  voice?: string | null;
  duration_ms?: number;
  audio_format?: string;
  fallback_occurred?: boolean;
}

export async function fetchVoiceSpeak(
  segments: SpeechSegment[],
  options?: { voice?: string; speed?: number },
): Promise<VoiceSpeakResponse> {
  const r = await apiFetch("/api/voice/speak", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ segments, ...options }),
  });
  if (!r.ok) throw new Error(`Voice speak API ${r.status}`);
  return r.json();
}

export async function fetchVoiceTranscribe(
  audioBase64: string,
  language: string,
): Promise<VoiceTranscribeResponse> {
  const r = await apiFetch("/api/voice/transcribe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ audio: audioBase64, language }),
  });
  if (!r.ok) throw new Error(`Voice transcribe API ${r.status}`);
  return r.json();
}
