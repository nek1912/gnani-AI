import { useState } from "react";
import type { GrievanceSubmission } from "@/lib/api";

interface EnglishDraft {
  category: string;
  sub_category: string;
  department: string;
  jurisdiction: string;
  title: string;
  description: string;
  location: {
    ward_number: string | null;
    locality: string | null;
    area: string | null;
    city: string | null;
    district: string | null;
    state: string | null;
  };
  submission: GrievanceSubmission | null;
}

export default function EnglishDraftViewPage() {
  const [draft] = useState<EnglishDraft | null>(() => {
    try {
      const raw = sessionStorage.getItem("grievance-english-draft");
      if (raw) return JSON.parse(raw) as EnglishDraft;
    } catch {
      // sessionStorage unavailable or corrupted
    }
    return null;
  });

  if (!draft) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6 sm:py-12">
        <h1 className="text-xl font-bold">English Grievance Draft</h1>
        <p className="mt-4 text-sm text-[var(--text-faint)]">
          No English draft available. This page is only shown when the grievance
          is filed in a non-English language.
        </p>
      </div>
    );
  }

  const { location, submission } = draft;
  const hasLocation = location && (location.ward_number || location.locality || location.area || location.city || location.state);

  return (
    <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6 sm:py-12">
      <h1 className="text-xl font-bold">English Grievance Draft</h1>
      <p className="mt-1 text-xs text-[var(--text-faint)]">
        Full English-language version of your grievance for submission.
      </p>

      <div className="mt-6 space-y-4">
        {/* Classification */}
        <section>
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--text-faint)]">
            Classification
          </h2>
          <div className="rounded-[var(--radius-md)] border border-[var(--border-soft)] bg-[var(--surface-elevated)] px-4 py-3 text-sm">
            <Row label="Category" value={draft.category} />
            <Row label="Sub-category" value={draft.sub_category} />
            <Row label="Department" value={draft.department} />
            <Row label="Jurisdiction" value={draft.jurisdiction} />
          </div>
        </section>

        {/* Title & Description */}
        <section>
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--text-faint)]">
            Title
          </h2>
          <p className="text-sm font-semibold">{draft.title}</p>
        </section>

        <section>
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--text-faint)]">
            Description
          </h2>
          <p className="text-sm leading-relaxed">{draft.description}</p>
        </section>

        {/* Location */}
        {hasLocation && (
          <section>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--text-faint)]">
              Location
            </h2>
            <div className="rounded-[var(--radius-md)] border border-[var(--border-soft)] bg-[var(--surface-elevated)] px-4 py-3 text-sm">
              {location.ward_number && <Row label="Ward Number" value={location.ward_number} />}
              {location.locality && <Row label="Locality" value={location.locality} />}
              {location.area && <Row label="Area" value={location.area} />}
              {location.city && <Row label="City" value={location.city} />}
              {location.state && <Row label="State" value={location.state} />}
            </div>
          </section>
        )}

        {/* Submission */}
        {submission && (
          <section>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--text-faint)]">
              Submission
            </h2>
            <div className="rounded-[var(--radius-md)] border border-[var(--border-soft)] bg-[var(--surface-elevated)] px-4 py-3 text-sm">
              {submission.portal_name && <Row label="Portal" value={submission.portal_name} />}
              {submission.portal_url && (
                <div className="flex items-start justify-between gap-3 py-1">
                  <span className="shrink-0 text-[var(--text-faint)]">URL</span>
                  <a
                    href={submission.portal_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-right font-medium text-[var(--accent-primary)] underline decoration-dotted hover:opacity-80"
                  >
                    {submission.portal_url}
                  </a>
                </div>
              )}
              {submission.department && <Row label="Department" value={submission.department} />}
              {submission.level && <Row label="Level" value={submission.level} />}

              {submission.steps.length > 0 && (
                <div className="mt-3">
                  <p className="mb-1 font-medium text-[var(--text-faint)]">Steps to Submit</p>
                  <ol className="list-decimal space-y-1 pl-5">
                    {submission.steps.map((step, i) => (
                      <li key={i} className="leading-relaxed">{step}</li>
                    ))}
                  </ol>
                </div>
              )}

              {submission.required_documents.length > 0 && (
                <div className="mt-3">
                  <p className="mb-1 font-medium text-[var(--text-faint)]">Required Documents</p>
                  <ul className="list-disc space-y-1 pl-5">
                    {submission.required_documents.map((doc, i) => (
                      <li key={i} className="leading-relaxed">{doc}</li>
                    ))}
                  </ul>
                </div>
              )}

              {submission.estimated_timeline && (
                <Row label="Estimated Timeline" value={submission.estimated_timeline} />
              )}

              {submission.disclaimer && (
                <div className="mt-3 rounded-[var(--radius-md)] bg-[var(--state-warning)]/10 px-3 py-2 text-xs text-[var(--state-warning)]">
                  <span className="font-semibold">Disclaimer: </span>
                  {submission.disclaimer}
                </div>
              )}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) return null;
  return (
    <div className="flex items-start justify-between gap-3 py-1">
      <span className="shrink-0 text-[var(--text-faint)]">{label}</span>
      <span className="text-right font-medium">{value}</span>
    </div>
  );
}
export { default as GrievanceDraftViewPage } from "./GrievanceDraftViewPage";
