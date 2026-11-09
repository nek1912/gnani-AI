import { useState } from "react";
import { useI18n } from "@/lib/i18n/provider";
import { IconCheck, IconBuilding, IconAlertTriangle } from "@/components/ui/Icons";

interface GrievanceClassification {
  category: string;
  sub_category: string;
  jurisdiction: string;
  title: string;
  description: string;
  department: string;
}

interface GrievanceClassificationPanelProps {
  classification: GrievanceClassification;
  onConfirm: () => void;
  onClarify: (clarification: string) => void;
  /** True once this table's own decision (Yes/No) has been made, or the
   * whole grievance has been finalized. Locks the buttons permanently --
   * this table can never be reopened or reverted. */
  isFinalized?: boolean;
  /** True while a request for THIS table is in flight. Locks the buttons
   * immediately on click, before the server has responded, so a second
   * click/tap cannot double-submit. */
  isBusy?: boolean;
}

export function GrievanceClassificationPanel({
  classification,
  onConfirm,
  onClarify,
  isFinalized = false,
  isBusy = false,
}: GrievanceClassificationPanelProps) {
  const { t } = useI18n();
  const [showClarify, setShowClarify] = useState(false);
  const [clarification, setClarification] = useState("");
  // Locked the instant a button on THIS table is clicked -- independent of
  // parent re-renders, so this exact table can never be double-submitted
  // and never reverts even if a later table's state changes.
  const [locallyLocked, setLocallyLocked] = useState(false);
  const locked = isFinalized || isBusy || locallyLocked;

  function handleConfirm() {
    if (locked) return;
    setLocallyLocked(true);
    onConfirm();
  }

  function handleClarify() {
    if (locked) return;
    setShowClarify(true);
  }

  function submitClarification() {
    if (locked) return;
    if (clarification.trim()) {
      setLocallyLocked(true);
      onClarify(clarification.trim());
      setShowClarify(false);
      setClarification("");
    }
  }

  return (
    <div className="mt-3 overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border-soft)] bg-[var(--surface-elevated)]">
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-[var(--border-soft)] bg-[var(--accent-primary)]/8 px-4 py-3">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--accent-primary)]/15 text-[var(--accent-primary)]">
          <IconBuilding className="h-3.5 w-3.5" />
        </span>
        <p className="text-sm font-semibold text-[var(--ink)]">
          {t("grievanceWizard.confirmTitle")}
        </p>
      </div>

      <div className="px-4 py-3">
        {/* Classification Table */}
        <table className="w-full text-sm">
          <tbody>
            <tr className="border-b border-[var(--border-soft)]">
              <td className="py-2 pr-4 font-medium text-[var(--text-faint)]">{t("grievanceCard.category")}</td>
              <td className="py-2 text-[var(--ink)]">{classification.category}</td>
            </tr>
            <tr className="border-b border-[var(--border-soft)]">
              <td className="py-2 pr-4 font-medium text-[var(--text-faint)]">{t("grievanceCard.subCategory")}</td>
              <td className="py-2 text-[var(--ink)]">{classification.sub_category}</td>
            </tr>
            <tr className="border-b border-[var(--border-soft)]">
              <td className="py-2 pr-4 font-medium text-[var(--text-faint)]">{t("grievanceCard.jurisdiction")}</td>
              <td className="py-2 text-[var(--ink)]">{classification.jurisdiction}</td>
            </tr>
            <tr className="border-b border-[var(--border-soft)]">
              <td className="py-2 pr-4 font-medium text-[var(--text-faint)]">{t("grievanceCard.titleLabel")}</td>
              <td className="py-2 text-[var(--ink)]">{classification.title}</td>
            </tr>
            <tr>
              <td className="py-2 pr-4 align-top font-medium text-[var(--text-faint)]">{t("grievanceCard.description")}</td>
              <td className="py-2 text-[var(--ink)]">{classification.description}</td>
            </tr>
          </tbody>
        </table>

        {/* Confirmation Buttons */}
        {!showClarify ? (
          <div className="mt-6 flex flex-col gap-3 sm:flex-row">
            <button
              type="button"
              onClick={handleConfirm}
              disabled={locked}
              className="flex flex-1 cursor-pointer items-center justify-center gap-2 rounded-[var(--radius-md)] border border-[var(--border-soft)] p-3 text-sm text-[var(--ink)] transition-colors hover:bg-[var(--cream)] hover:border-[var(--state-success)] disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <IconCheck className="h-4 w-4 text-[var(--state-success)]" />
              {t("grievanceWizard.confirmYes")}
            </button>
            <button
              type="button"
              onClick={handleClarify}
              disabled={locked}
              className="flex flex-1 cursor-pointer items-center justify-center gap-2 rounded-[var(--radius-md)] border border-[var(--border-soft)] p-3 text-sm text-[var(--ink)] transition-colors hover:bg-[var(--cream)] hover:border-[var(--state-warning)] disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <IconAlertTriangle className="h-4 w-4 text-[var(--state-warning)]" />
              {t("grievanceWizard.confirmNo")}
            </button>
          </div>
        ) : (
          <div className="mt-6">
            <label className="mb-2 block text-sm font-medium text-[var(--text-primary)]">
              {t("grievanceWizard.reviseLabel")}
            </label>
            <textarea
              className="w-full rounded-[var(--radius-md)] border border-[var(--border-soft)] bg-[var(--surface-base)] p-3 text-sm text-[var(--ink)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)]"
              rows={4}
              value={clarification}
              onChange={(e) => setClarification(e.target.value)}
            />
            <div className="mt-3 flex justify-end">
              <button
                type="button"
                onClick={submitClarification}
                disabled={!clarification.trim() || locked}
                className="rounded-[var(--radius-md)] bg-[var(--accent-primary)] px-4 py-2 text-sm font-medium text-[var(--accent-contrast)] transition-colors hover:bg-[var(--accent-hover)] disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {t("grievanceWizard.reviseSubmit")}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
