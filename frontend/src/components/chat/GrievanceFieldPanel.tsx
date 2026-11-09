import { useState } from "react";
import { useI18n } from "@/lib/i18n/provider";
import { IconChevronRight } from "@/components/ui/Icons";

interface GrievanceField {
  field: string;
  field_label: string;
  question: string;
  input_type: "int" | "date" | "text";
  mandatory: boolean;
  value: string | null;
}

interface GrievanceFieldsSchema {
  mandatory_fields: GrievanceField[];
  optional_fields: GrievanceField[];
}

interface GrievanceFieldPanelProps {
  fieldsSchema: GrievanceFieldsSchema;
  draftSummary: {
    category: string;
    sub_category: string;
    jurisdiction: string;
    title: string;
    description: string;
    department: string;
  };
  onSubmit: (answers: Record<string, string>) => void;
  onCancel: () => void;
  isFinalized?: boolean;
  isSubmitting?: boolean;
}

export function GrievanceFieldPanel({
  fieldsSchema,
  draftSummary,
  onSubmit,
  onCancel,
  isFinalized = false,
  isSubmitting = false,
}: GrievanceFieldPanelProps) {
  const { t } = useI18n();
  const [showOptional, setShowOptional] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>(() => {
    const seeded: Record<string, string> = {};
    for (const f of [...fieldsSchema.mandatory_fields, ...fieldsSchema.optional_fields]) {
      if (f.value) seeded[f.field] = f.value;
    }
    return seeded;
  });

  const activeList = showOptional ? fieldsSchema.optional_fields : fieldsSchema.mandatory_fields;
  const activeField = activeList[activeIndex];
  const mandatoryComplete = fieldsSchema.mandatory_fields.every(
    (f) => (answers[f.field] ?? "").trim().length > 0
  );

  function handleFieldChange(value: string) {
    if (!activeField) return;
    // For integer fields, strip non-digit characters
    if (activeField.input_type === "int") {
      value = value.replace(/[^0-9]/g, "");
    }
    setAnswers((prev) => ({ ...prev, [activeField.field]: value }));
  }

  function handleSubmit() {
    onSubmit(answers);
  }

  return (
    <div className="mt-3 overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border-soft)] bg-[var(--surface-elevated)]">
      {/* Header */}
      <div className="border-b border-[var(--border-soft)] bg-[var(--cream)] px-4 py-3">
        <p className="text-sm font-semibold text-[var(--ink)]">
          {showOptional ? t("grievanceWizard.optionalTab") : t("grievanceWizard.mandatoryTab")}
        </p>
      </div>

      <div className="px-4 py-3">
        {/* Tabs */}
        <div className="flex flex-wrap gap-2 border-b border-[var(--border-soft)] pb-3">
          {activeList.map((f, i) => (
            <button
              key={f.field}
              type="button"
              onClick={() => setActiveIndex(i)}
              className={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                i === activeIndex
                  ? "bg-[var(--accent-primary)] text-[var(--accent-contrast)]"
                  : "bg-[var(--cream)] text-[var(--ink)] hover:bg-[var(--cream-2)]"
              }`}
            >
              {f.field_label || f.field.replace(/_/g, " ")}
              {(answers[f.field] ?? "").trim() && " ✓"}
            </button>
          ))}
        </div>

        {/* Field Counter */}
        <p className="mt-3 text-xs font-semibold uppercase tracking-wide text-[var(--text-faint)]">
          {showOptional ? t("grievanceWizard.optionalTab") : t("grievanceWizard.mandatoryTab")} ·{" "}
          {t("grievanceWizard.fieldOf", { n: activeIndex + 1, total: activeList.length })}
        </p>

        {/* Field Input */}
        {activeField && (
          <div className="mt-4">
            <label className="mb-2 block text-sm font-medium text-[var(--text-primary)]">
              {activeField.question}
            </label>
            {activeField.input_type === "text" && activeField.field.includes("description") ? (
              <textarea
                className="w-full rounded-[var(--radius-md)] border border-[var(--border-soft)] bg-[var(--surface-base)] p-3 text-sm text-[var(--ink)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] disabled:opacity-50 disabled:cursor-not-allowed"
                rows={4}
                value={answers[activeField.field] ?? ""}
                onChange={(e) => handleFieldChange(e.target.value)}
                disabled={isFinalized}
              />
            ) : (
              <input
                type={activeField.input_type === "date" ? "date" : "text"}
                inputMode={activeField.input_type === "int" ? "numeric" : undefined}
                pattern={activeField.input_type === "int" ? "[0-9]*" : undefined}
                className="w-full rounded-[var(--radius-md)] border border-[var(--border-soft)] bg-[var(--surface-base)] p-3 text-sm text-[var(--ink)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] disabled:opacity-50 disabled:cursor-not-allowed"
                value={answers[activeField.field] ?? ""}
                onChange={(e) => handleFieldChange(e.target.value)}
                disabled={isFinalized}
              />
            )}
          </div>
        )}

        {/* Navigation Buttons */}
        <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
          {showOptional ? (
            <button
              type="button"
              onClick={() => {
                setShowOptional(false);
                setActiveIndex(fieldsSchema.mandatory_fields.length - 1);
              }}
              disabled={isFinalized}
              className="rounded-[var(--radius-md)] border border-[var(--border-soft)] px-4 py-2 text-sm font-medium text-[var(--ink)] transition-colors hover:bg-[var(--cream)] disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {t("grievanceWizard.backToMandatory")}
            </button>
          ) : (
            <div />
          )}

          <div className="flex gap-3">
            {!showOptional && activeIndex < fieldsSchema.mandatory_fields.length - 1 && (
              <button
                type="button"
                onClick={() => setActiveIndex((i) => i + 1)}
                disabled={isFinalized}
                className="rounded-[var(--radius-md)] border border-[var(--border-soft)] px-4 py-2 text-sm font-medium text-[var(--ink)] transition-colors hover:bg-[var(--cream)] disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {t("common.next")}
              </button>
            )}
            {showOptional && activeIndex < fieldsSchema.optional_fields.length - 1 && (
              <button
                type="button"
                onClick={() => setActiveIndex((i) => i + 1)}
                disabled={isFinalized}
                className="rounded-[var(--radius-md)] border border-[var(--border-soft)] px-4 py-2 text-sm font-medium text-[var(--ink)] transition-colors hover:bg-[var(--cream)] disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {t("common.next")}
              </button>
            )}

            {!showOptional && activeIndex === fieldsSchema.mandatory_fields.length - 1 && (
              <>
                {fieldsSchema.optional_fields.length > 0 && (
                  <button
                    type="button"
                    onClick={() => {
                      setShowOptional(true);
                      setActiveIndex(0);
                    }}
                    disabled={isFinalized || isSubmitting}
                    className="rounded-[var(--radius-md)] border border-[var(--border-soft)] px-4 py-2 text-sm font-medium text-[var(--ink)] transition-colors hover:bg-[var(--cream)] disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {t("grievanceWizard.addOptional")}
                  </button>
                )}
                <button
                  type="button"
                  onClick={handleSubmit}
                  disabled={!mandatoryComplete || isFinalized || isSubmitting}
                  className="rounded-[var(--radius-md)] bg-[var(--accent-primary)] px-4 py-2 text-sm font-medium text-[var(--accent-contrast)] transition-colors hover:bg-[var(--accent-hover)] disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isSubmitting ? t("grievanceWizard.submitting") : t("grievanceWizard.submit")}
                </button>
              </>
            )}

            {showOptional && activeIndex === fieldsSchema.optional_fields.length - 1 && (
              <button
                type="button"
                onClick={handleSubmit}
                disabled={!mandatoryComplete || isFinalized || isSubmitting}
                className="rounded-[var(--radius-md)] bg-[var(--accent-primary)] px-4 py-2 text-sm font-medium text-[var(--accent-contrast)] transition-colors hover:bg-[var(--accent-hover)] disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isSubmitting ? t("grievanceWizard.submitting") : t("grievanceWizard.submit")}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
