import { useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import type { Grievance } from "@/lib/api";
import { useI18n } from "@/lib/i18n/provider";
import {
  IconCheck,
  IconBuilding,
  IconPin,
  IconDoc,
  IconClock,
  IconAlertTriangle,
  IconChevronRight,
} from "@/components/ui/Icons";

/**
 * Renders the canonical, language-neutral `grievance` object as a clearly
 * separated, labeled card — reference, category/department/jurisdiction,
 * description, location, submission route, steps, documents, timeline and
 * disclaimer each get their own section with a divider between them.
 *
 * This component ONLY reads structured fields off `grievance`. It never
 * parses the free-text `answer` to reconstruct data, so the same card
 * renders correctly regardless of the user's selected language — only the
 * section labels (via `t()`) change, never the underlying values.
 */

function Divider() {
  return <div className="my-3 border-t border-[var(--border-soft)]" />;
}

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-[var(--text-faint)]">
      {children}
    </p>
  );
}

/**
 * Field keys arrive from the grievance backend as snake_case. Turn them into
 * human-readable English labels.
 *
 * Initialisms must stay uppercase ("application_id" -> "Application ID"). A naive
 * title-caser produces "Application Id", which reads as a typo to a citizen
 * filling in a government form, so the initialism set is explicit rather than
 * guessed.
 *
 * Entries are the words that appear as their own segment in real backend field
 * keys (see backend/app/grievance/field_detector.py). Words that merely CONTAIN
 * an initialism must not be added: "identity" is not an initialism, and
 * "aadhaar" is deliberately absent because the backend's own label for it is
 * "Aadhaar Number", not "AADHAAR".
 */
const FIELD_INITIALISMS = new Set([
  "cibil",
  "discom",
  "esi",
  "fps",
  "gst",
  "id",
  "ifsc",
  "kcc",
  "pan",
  "pf",
  "pin",
  "rte",
  "rto",
  "rti",
  "sms",
  "upi",
  "url",
]);

function humanizeFieldKey(key: string): string {
  return key
    .split("_")
    .filter(Boolean)
    .map((word) => {
      const lower = word.toLowerCase();
      if (FIELD_INITIALISMS.has(lower)) return lower.toUpperCase();
      return lower.charAt(0).toUpperCase() + lower.slice(1);
    })
    .join(" ");
}

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) return null;
  return (
    <div className="flex items-start justify-between gap-3 py-1 text-sm">
      <span className="shrink-0 text-[var(--text-faint)]">{label}</span>
      <span className="text-right font-medium text-[var(--ink)]">{value}</span>
    </div>
  );
}

export function GrievanceCard({ grievance }: { grievance: Grievance }) {
  const { t } = useI18n();
  const router = useNavigate();
  const [showEnglishDraft, setShowEnglishDraft] = useState(false);

  const location = grievance.location;
  const submission = grievance.submission;
  const description = grievance.description;
  // Only worth offering an "English submission draft" preview when the
  // localized display text actually differs from the canonical English
  // text — for English-language users these are identical.
  const hasEnglishPreview =
    !!description?.normalized &&
    description.normalized.trim() !== description.display?.trim();

  const hasAnyLocation =
    !!location &&
    (location.ward_number || location.locality || location.area || location.city || location.state);

  return (
    <div className="mt-3 overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border-soft)] bg-[var(--surface-elevated)]">
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-[var(--border-soft)] bg-[var(--state-success)]/8 px-4 py-3">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--state-success)]/15 text-[var(--state-success)]">
          <IconCheck className="h-3.5 w-3.5" />
        </span>
        <p className="text-sm font-semibold text-[var(--ink)]">
          {t("grievanceCard.ready")}
        </p>
      </div>

      <div className="px-4 py-3">
        {/* Grievance details */}
        <SectionLabel>{t("grievanceCard.titleLabel")}</SectionLabel>
        <div className="flex items-start gap-2">
          <IconBuilding className="mt-0.5 h-4 w-4 shrink-0 text-[var(--text-faint)]" />
          <p className="text-sm font-semibold text-[var(--ink)]">{grievance.title}</p>
        </div>
        <div className="mt-2">
          <Field label={t("grievanceCard.reference")} value={grievance.reference} />
          <Field label={t("grievanceCard.category")} value={grievance.category} />
          <Field label={t("grievanceCard.subCategory")} value={grievance.sub_category} />
          <Field label={t("grievanceCard.department")} value={grievance.department} />
          <Field label={t("grievanceCard.jurisdiction")} value={grievance.jurisdiction} />
        </div>

        {/* Description — shows the user-facing draft, localized to the
            user's preferred language. This is a clean, canonical-derived
            presentation string, NOT the raw citizen input and NOT an
            intermediate/partially-translated string. The immutable raw
            input remains available separately via the English submission
            preview toggle below, only where it differs from this. */}
        {description?.display && (
          <>
            <Divider />
            <SectionLabel>{t("grievanceCard.description")}</SectionLabel>
            <p className="text-sm leading-relaxed text-[var(--ink)]">
              {description.display}
            </p>

            {hasEnglishPreview && (
              <div className="mt-2">
                <button
                  type="button"
                  onClick={() => setShowEnglishDraft((v) => !v)}
                  className="text-xs font-medium text-[var(--accent-primary)] underline decoration-dotted hover:opacity-80"
                >
                  {showEnglishDraft
                    ? t("grievanceCard.hideEnglishDraft")
                    : t("grievanceCard.showEnglishDraft")}
                </button>
                {showEnglishDraft && (
                  <div className="mt-2 rounded-[var(--radius-md)] border border-[var(--border-soft)] bg-[var(--surface-base)] px-3 py-2">
                    <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-[var(--text-faint)]">
                      {t("grievanceCard.englishSubmissionDraft")}
                    </p>
                    <p className="text-sm leading-relaxed text-[var(--ink)]">
                      {description.normalized}
                    </p>
                  </div>
                )}
              </div>
            )}

            {/* Full-page English draft — the entire grievance (fields,
                classification, submission steps, documents, timeline,
                disclaimer) rendered in English on its own sub-page.
                Only shown when the backend attached an English mirror,
                i.e. the workflow ran in a non-English language. */}
            {grievance.english && (
              <div className="mt-2">
                <button
                  type="button"
                  onClick={() => {
                    try {
                      sessionStorage.setItem(
                        "grievance-english-draft",
                        JSON.stringify(grievance.english),
                      );
                    } catch {
                      // sessionStorage unavailable (private mode, etc.) — the
                      // draft page will show its own empty-state in that case.
                    }
                    router("/grievance/draft/view");
                  }}
                  className="inline-flex items-center gap-1 text-xs font-medium text-[var(--accent-primary)] underline decoration-dotted hover:opacity-80"
                >
                  {t("grievanceCard.openEnglishDraftPage")}
                  <IconChevronRight className="h-3 w-3" />
                </button>
              </div>
            )}
          </>
        )}

        {/* Location */}
        {hasAnyLocation && (
          <>
            <Divider />
            <SectionLabel>
              <span className="inline-flex items-center gap-1.5">
                <IconPin className="h-3.5 w-3.5" />
                {t("grievanceCard.location")}
              </span>
            </SectionLabel>
            <Field label={t("grievanceCard.wardNumber")} value={location?.ward_number} />
            <Field label={t("grievanceCard.locality")} value={location?.locality} />
            <Field label={t("grievanceCard.area")} value={location?.area} />
            <Field label={t("grievanceCard.city")} value={location?.city} />
            <Field label={t("grievanceCard.state")} value={location?.state} />
          </>
        )}

        {/* Structured fields (farmer_name, application_id, etc.) */}
        {grievance.fields && Object.keys(grievance.fields).length > 0 && (
          <>
            <Divider />
            <SectionLabel>{t("grievanceCard.fields")}</SectionLabel>
            {Object.keys(grievance.fields).map((key) => {
              const value = grievance.fields![key];
              const camelKey = key.replace(/_([a-z])/g, (_, c) => c.toUpperCase());
              const i18nKey = `field.${camelKey}`;
              const translated = t(i18nKey as Parameters<typeof t>[0]);
              const label = translated !== i18nKey ? translated : humanizeFieldKey(key);
              return (
                <Field
                  key={key}
                  label={label}
                  value={value}
                />
              );
            })}
          </>
        )}

        {/* Submission */}
        {submission && (submission.portal_name || submission.portal_url) && (
          <>
            <Divider />
            <SectionLabel>{t("grievanceCard.submission")}</SectionLabel>
            <Field label={t("grievanceCard.portal")} value={submission.portal_name} />
            {submission.portal_url && (
              <div className="flex items-start justify-between gap-3 py-1 text-sm">
                <span className="shrink-0 text-[var(--text-faint)]">{t("grievanceCard.url")}</span>
                {/^https?:\/\//.test(submission.portal_url) ? (
                  <a
                    href={submission.portal_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-right font-medium text-[var(--accent-primary)] underline decoration-dotted hover:opacity-80"
                  >
                    {submission.portal_url}
                    <IconChevronRight className="h-3 w-3 shrink-0" />
                  </a>
                ) : (
                  <span className="max-w-[70%] text-right text-[var(--ink)]">
                    {submission.portal_url}
                  </span>
                )}
              </div>
            )}
            <Field label={t("grievanceCard.department")} value={submission.department} />
            <Field label={t("grievanceCard.level")} value={submission.level} />

            {submission.steps && submission.steps.length > 0 && (
              <>
                <Divider />
                <SectionLabel>{t("grievanceCard.steps")}</SectionLabel>
                <ol className="list-decimal space-y-1.5 pl-5 text-sm text-[var(--ink)]">
                  {submission.steps.map((step, i) => (
                    <li key={i} className="leading-relaxed">{step}</li>
                  ))}
                </ol>
              </>
            )}

            {submission.required_documents && submission.required_documents.length > 0 && (
              <>
                <Divider />
                <SectionLabel>
                  <span className="inline-flex items-center gap-1.5">
                    <IconDoc className="h-3.5 w-3.5" />
                    {t("grievanceCard.documents")}
                  </span>
                </SectionLabel>
                <ul className="list-disc space-y-1 pl-5 text-sm text-[var(--ink)]">
                  {submission.required_documents.map((doc, i) => (
                    <li key={i} className="leading-relaxed">{doc}</li>
                  ))}
                </ul>
              </>
            )}

            {submission.estimated_timeline && (
              <>
                <Divider />
                <SectionLabel>
                  <span className="inline-flex items-center gap-1.5">
                    <IconClock className="h-3.5 w-3.5" />
                    {t("grievanceCard.timeline")}
                  </span>
                </SectionLabel>
                <p className="text-sm font-medium text-[var(--ink)]">
                  {submission.estimated_timeline}
                </p>
              </>
            )}

            {submission.disclaimer && (
              <>
                <Divider />
                <div className="flex items-start gap-2 rounded-[var(--radius-md)] bg-[var(--state-warning)]/10 px-3 py-2 text-xs text-[var(--state-warning)]">
                  <IconAlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <p>
                    <span className="font-semibold">{t("grievanceCard.disclaimer")}: </span>
                    {submission.disclaimer}
                  </p>
                </div>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
