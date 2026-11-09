import { useState, useCallback, useMemo } from "react";
import { useI18n } from "@/lib/i18n/provider";
import { createSpeechService } from "@/lib/speech";
import {
  detectGrievance,
  clarifyGrievance,
  getGrievanceFields,
  answerGrievanceField,
  finalizeGrievanceDraft,
  type Grievance,
} from "@/lib/api";
import { Stepper } from "@/components/ui/Stepper";
import {
  IconBuilding,
  IconCheck,
  IconAlertTriangle,
  IconChevronRight,
  IconShield,
  IconClock,
  IconRefresh,
  IconMic,
  IconInfo,
} from "@/components/ui/Icons";

type Step = "intake" | "classification" | "fields" | "review";

interface Classification {
  category: string;
  sub_category: string;
  jurisdiction: string;
  title: string;
  description: string;
  department: string;
}

interface FieldSpec {
  field: string;
  field_label: string;
  question: string;
  input_type: "int" | "date" | "text";
  mandatory: boolean;
  value: string | null;
}

const STEP_ORDER: Step[] = ["intake", "classification", "fields", "review"];
const STEP_LABELS_KEY = ["grievance.step1", "grievance.step2", "grievance.step3", "grievance.step4"] as const;

const EXAMPLES = [
  "Loan not sanctioned",
  "Payment delayed",
  "Membership issue",
  "Pension not received",
  "Subsidy not credited",
];

function generateId() {
  return crypto.randomUUID();
}

export default function GrievancePage() {
  const { t, locale } = useI18n();

  const [step, setStep] = useState<Step>("intake");
  const [complaint, setComplaint] = useState("");
  const [classification, setClassification] = useState<Classification | null>(null);
  const [conversationId] = useState(() => generateId());
  const [userId] = useState(() => generateId());

  const [showClarify, setShowClarify] = useState(false);
  const [clarification, setClarification] = useState("");
  const [classificationBusy, setClassificationBusy] = useState(false);

  const [mandatoryFields, setMandatoryFields] = useState<FieldSpec[]>([]);
  const [optionalFields, setOptionalFields] = useState<FieldSpec[]>([]);
  const [fieldAnswers, setFieldAnswers] = useState<Record<string, string>>({});
  const [activeFieldIdx, setActiveFieldIdx] = useState(0);
  const [showOptional, setShowOptional] = useState(false);
  const [fieldsBusy, setFieldsBusy] = useState(false);

  const [grievance, setGrievance] = useState<Grievance | null>(null);

  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const startOver = useCallback(() => {
    setStep("intake");
    setComplaint("");
    setClassification(null);
    setMandatoryFields([]);
    setOptionalFields([]);
    setFieldAnswers({});
    setActiveFieldIdx(0);
    setShowOptional(false);
    setShowClarify(false);
    setClarification("");
    setClassificationBusy(false);
    setFieldsBusy(false);
    setGrievance(null);
    setError("");
    setLoading(false);
  }, []);

  const currentStepIdx = STEP_ORDER.indexOf(step);
  const steps = STEP_LABELS_KEY.map((k) => t(k));
  const speech = useMemo(() => createSpeechService(), []);
  const [listening, setListening] = useState(false);

  const handleVoiceInput = useCallback(() => {
    if (listening) return;
    setListening(true);
    const stop = speech.listen(locale, (transcript) => {
      setComplaint((prev) => (prev ? prev + " " + transcript : transcript));
      setListening(false);
    });
    setTimeout(() => {
      stop();
      setListening(false);
    }, 15000);
  }, [listening, speech, locale]);

  const handleIntake = useCallback(async () => {
    if (!complaint.trim() || loading) return;
    setLoading(true);
    setError("");
    try {
      const result = await detectGrievance({
        message: complaint.trim(),
        conversation_id: conversationId,
        user_id: userId,
      });
      if (result.status === "ok" && result.draft) {
        setClassification({
          category: result.draft.category,
          sub_category: result.draft.sub_category,
          jurisdiction: result.draft.jurisdiction,
          title: result.draft.title,
          description: result.draft.description,
          department: result.draft.department,
        });
        setStep("classification");
      } else {
        setError(result.response || "Could not classify your complaint. Please try again.");
      }
    } catch {
      setError("Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  }, [complaint, conversationId, userId, loading]);

  const handleConfirm = useCallback(async () => {
    setClassificationBusy(true);
    try {
      const fieldsResult = await getGrievanceFields(conversationId, "en");
      if (fieldsResult.status === "ok") {
        setMandatoryFields(fieldsResult.mandatory_fields || []);
        setOptionalFields(fieldsResult.optional_fields || []);
        const seeded: Record<string, string> = {};
        for (const f of [...(fieldsResult.mandatory_fields || []), ...(fieldsResult.optional_fields || [])]) {
          if (f.value) seeded[f.field] = f.value;
        }
        setFieldAnswers(seeded);
        setActiveFieldIdx(0);
        setShowOptional(false);
        setStep("fields");
      }
    } catch {
      setError("Failed to load form fields. Please try again.");
    } finally {
      setClassificationBusy(false);
    }
  }, [conversationId]);

  const handleClarify = useCallback(async () => {
    if (!clarification.trim() || classificationBusy) return;
    setClassificationBusy(true);
    setError("");
    try {
      const result = await clarifyGrievance({
        conversation_id: conversationId,
        complaint: clarification.trim(),
        language: "en",
      });
      if (result.status === "ok" && result.draft_summary) {
        setClassification({
          category: result.draft_summary.category,
          sub_category: result.draft_summary.sub_category,
          jurisdiction: result.draft_summary.jurisdiction,
          title: result.draft_summary.title,
          description: result.draft_summary.description,
          department: result.draft_summary.department,
        });
        setShowClarify(false);
        setClarification("");
      }
    } catch {
      setError("Failed to reclassify. Please try again.");
    } finally {
      setClassificationBusy(false);
    }
  }, [clarification, conversationId, classificationBusy]);

  const activeList = showOptional ? optionalFields : mandatoryFields;
  const activeField = activeList[activeFieldIdx];
  const mandatoryComplete = mandatoryFields.every(
    (f) => (fieldAnswers[f.field] ?? "").trim().length > 0
  );

  const handleFieldChange = useCallback((value: string) => {
    if (!activeField) return;
    if (activeField.input_type === "int") {
      value = value.replace(/[^0-9]/g, "");
    }
    setFieldAnswers((prev) => ({ ...prev, [activeField.field]: value }));
  }, [activeField]);

  const handleFieldsSubmit = useCallback(async () => {
    if (fieldsBusy) return;
    setFieldsBusy(true);
    setError("");
    try {
      for (const [field, value] of Object.entries(fieldAnswers)) {
        if (value.trim()) {
          await answerGrievanceField({
            conversation_id: conversationId,
            field,
            value: value.trim(),
          });
        }
      }
      const result = await finalizeGrievanceDraft({
        conversation_id: conversationId,
        language: "en",
      });
      if (result.status === "ok" && result.grievance) {
        setGrievance(result.grievance);
        setStep("review");
      }
    } catch {
      setError("Failed to finalize grievance. Please try again.");
    } finally {
      setFieldsBusy(false);
    }
  }, [fieldAnswers, conversationId, fieldsBusy]);

  return (
    <div className="page-container px-4 py-10 sm:px-6 sm:py-12 md:py-16">
      <div className="mx-auto max-w-5xl">
        {/* ── Header ──────────────────────────────────────── */}
        <div className="text-center">
          <h1 className="display text-3xl tracking-tight text-[var(--ink)] sm:text-4xl">
            {t("grievance.title")}
          </h1>
          <p className="mt-2 text-base text-[var(--text-body)]">
            {t("grievance.subtitle")}
          </p>
          <div className="mt-4 flex items-center justify-center gap-4 text-xs text-[var(--text-tertiary)]">
            <span className="inline-flex items-center gap-1.5">
              <IconShield className="h-3.5 w-3.5" />
              {t("grievance.secure")}
            </span>
            <span className="h-1 w-1 rounded-full bg-[var(--text-faint)]" />
            <span className="inline-flex items-center gap-1.5">
              <IconClock className="h-3.5 w-3.5" />
              ~3 min
            </span>
            <span className="h-1 w-1 rounded-full bg-[var(--text-faint)]" />
            <span className="inline-flex items-center gap-1.5">
              <IconRefresh className="h-3.5 w-3.5" />
              {t("grievance.track")}
            </span>
          </div>
        </div>

        {/* ── Stepper ─────────────────────────────────────── */}
        <div className="mt-10">
          <Stepper steps={steps} current={currentStepIdx} />
        </div>

        {error && (
          <div className="mt-6 rounded-[var(--radius-md)] border border-[var(--state-error)]/30 bg-[var(--state-error)]/8 px-4 py-3 text-sm text-[var(--state-error)]">
            {error}
          </div>
        )}

        {/* ── Main Content ─────────────────────────────────── */}
        <div className="mt-10 max-w-2xl mx-auto">
          {/* ── Step 1: Intake ─────────────────────────── */}
          {step === "intake" && (
              <div className="rounded-[var(--radius-lg)] border border-[var(--border-soft)] bg-[var(--surface-elevated)] shadow-[var(--shadow-sm)]">
                <div className="p-6">
                  <h2 className="text-base font-semibold text-[var(--ink)]">
                    {t("grievanceWizard.startPrompt")}
                  </h2>
                  <textarea
                    value={complaint}
                    onChange={(e) => setComplaint(e.target.value)}
                    rows={5}
                    placeholder={t("grievanceWizard.complaintPlaceholder")}
                    className="mt-4 w-full rounded-[var(--radius-md)] border border-[var(--border-soft)] bg-[var(--surface-base)] p-4 text-sm text-[var(--ink)] placeholder:text-[var(--text-faint)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)]"
                  />
                  <button
                    type="button"
                    onClick={handleVoiceInput}
                    disabled={listening}
                    className={`mt-3 inline-flex items-center gap-2 text-sm font-medium transition-colors ${
                      listening
                        ? "text-[var(--state-error)] animate-pulse"
                        : "text-[var(--accent-primary)] hover:text-[var(--accent-hover)]"
                    }`}
                  >
                    <IconMic className="h-4 w-4" />
                    {listening ? "Listening…" : t("grievanceWizard.voiceInput")}
                  </button>
                </div>
                <div className="border-t border-[var(--border-soft)] bg-[var(--cream)]/50 px-6 py-4">
                  <p className="text-xs font-medium text-[var(--text-tertiary)]">
                    {t("grievanceWizard.tryExample")}
                  </p>
                  <div className="mt-2.5 flex flex-wrap gap-2">
                    {EXAMPLES.map((ex) => (
                      <button
                        key={ex}
                        type="button"
                        onClick={() => setComplaint(ex)}
                        className="rounded-full border border-[var(--border-soft)] bg-[var(--surface-base)] px-3 py-1.5 text-xs font-medium text-[var(--ink)] transition-colors hover:border-[var(--accent-primary)]/40 hover:bg-[var(--accent-primary)]/5 hover:text-[var(--accent-primary)]"
                      >
                        {ex}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="border-t border-[var(--border-soft)] px-6 py-4">
                  <button
                    type="button"
                    onClick={handleIntake}
                    disabled={!complaint.trim() || loading}
                    className="inline-flex w-full items-center justify-center gap-2 rounded-[var(--radius-cta)] bg-[var(--accent-primary)] px-5 py-3 text-sm font-semibold text-[var(--accent-contrast)] transition-colors hover:bg-[var(--accent-hover)] disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {loading ? (
                      <>
                        <span className="h-4 w-4 animate-spin rounded-full border-2 border-[var(--accent-contrast)]/30 border-t-[var(--accent-contrast)]" />
                        {t("grievanceWizard.detecting")}
                      </>
                    ) : (
                      <>
                        {t("common.next")}
                        <IconChevronRight className="h-4 w-4" />
                      </>
                    )}
                  </button>
                </div>
              </div>
            )}

            {/* ── Step 2: Classification ────────────────── */}
            {step === "classification" && classification && (
              <div className="rounded-[var(--radius-lg)] border border-[var(--border-soft)] bg-[var(--surface-elevated)] shadow-[var(--shadow-sm)]">
                <div className="flex items-center gap-3 border-b border-[var(--border-soft)] px-6 py-4">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--accent-primary)]/10 text-[var(--accent-primary)]">
                    <IconBuilding className="h-4 w-4" />
                  </span>
                  <div>
                    <p className="text-sm font-semibold text-[var(--ink)]">
                      {t("grievanceWizard.confirmTitle")}
                    </p>
                    <p className="text-xs text-[var(--text-tertiary)]">
                      {classification.department}
                    </p>
                  </div>
                </div>

                <div className="px-4 sm:px-6 py-5">
                  <div className="space-y-3">
                    <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between sm:gap-3 sm:py-3 sm:border-b sm:border-[var(--border-soft)]">
                      <span className="text-xs font-medium text-[var(--text-faint)] sm:py-3">{t("grievanceCard.category")}</span>
                      <span className="text-sm font-medium text-[var(--ink)] sm:py-3">{classification.category}</span>
                    </div>
                    <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between sm:gap-3 sm:py-3 sm:border-b sm:border-[var(--border-soft)]">
                      <span className="text-xs font-medium text-[var(--text-faint)] sm:py-3">{t("grievanceCard.subCategory")}</span>
                      <span className="text-sm font-medium text-[var(--ink)] sm:py-3">{classification.sub_category}</span>
                    </div>
                    <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between sm:gap-3 sm:py-3 sm:border-b sm:border-[var(--border-soft)]">
                      <span className="text-xs font-medium text-[var(--text-faint)] sm:py-3">{t("grievanceCard.jurisdiction")}</span>
                      <span className="text-sm font-medium text-[var(--ink)] sm:py-3">{classification.jurisdiction}</span>
                    </div>
                    <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between sm:gap-3 sm:py-3 sm:border-b sm:border-[var(--border-soft)]">
                      <span className="text-xs font-medium text-[var(--text-faint)] sm:py-3">{t("grievanceCard.titleLabel")}</span>
                      <span className="text-sm font-medium text-[var(--ink)] sm:py-3">{classification.title}</span>
                    </div>
                    <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between sm:gap-3 sm:py-3">
                      <span className="text-xs font-medium text-[var(--text-faint)] sm:py-3">{t("grievanceCard.description")}</span>
                      <span className="text-sm font-medium text-[var(--ink)] sm:py-3">{classification.description}</span>
                    </div>
                  </div>
                </div>

                <div className="border-t border-[var(--border-soft)] px-6 py-4">
                  {!showClarify ? (
                    <div className="flex flex-col gap-3 sm:flex-row">
                      <button
                        type="button"
                        onClick={handleConfirm}
                        disabled={classificationBusy}
                        className="flex flex-1 cursor-pointer items-center justify-center gap-2 rounded-[var(--radius-md)] border border-[var(--state-success)]/40 bg-[var(--state-success)]/8 p-3 text-sm font-medium text-[var(--state-success)] transition-colors hover:bg-[var(--state-success)]/15 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        <IconCheck className="h-4 w-4" />
                        {t("grievanceWizard.confirmYes")}
                      </button>
                      <button
                        type="button"
                        onClick={() => setShowClarify(true)}
                        disabled={classificationBusy}
                        className="flex flex-1 cursor-pointer items-center justify-center gap-2 rounded-[var(--radius-md)] border border-[var(--state-warning)]/40 bg-[var(--state-warning)]/8 p-3 text-sm font-medium text-[var(--state-warning)] transition-colors hover:bg-[var(--state-warning)]/15 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        <IconAlertTriangle className="h-4 w-4" />
                        {t("grievanceWizard.confirmNo")}
                      </button>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      <label className="block text-sm font-medium text-[var(--text-primary)]">
                        {t("grievanceWizard.reviseLabel")}
                      </label>
                      <textarea
                        className="w-full rounded-[var(--radius-md)] border border-[var(--border-soft)] bg-[var(--surface-base)] p-3 text-sm text-[var(--ink)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)]"
                        rows={4}
                        value={clarification}
                        onChange={(e) => setClarification(e.target.value)}
                      />
                      <div className="flex justify-end gap-3">
                        <button
                          type="button"
                          onClick={() => { setShowClarify(false); setClarification(""); }}
                          className="rounded-[var(--radius-md)] border border-[var(--border-soft)] px-4 py-2 text-sm font-medium text-[var(--ink)] transition-colors hover:bg-[var(--cream)]"
                        >
                          {t("common.back")}
                        </button>
                        <button
                          type="button"
                          onClick={handleClarify}
                          disabled={!clarification.trim() || classificationBusy}
                          className="rounded-[var(--radius-md)] bg-[var(--accent-primary)] px-4 py-2 text-sm font-medium text-[var(--accent-contrast)] transition-colors hover:bg-[var(--accent-hover)] disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          {t("grievanceWizard.reviseSubmit")}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* ── Step 3: Fields ────────────────────────── */}
            {step === "fields" && (
              <div className="rounded-[var(--radius-lg)] border border-[var(--border-soft)] bg-[var(--surface-elevated)] shadow-[var(--shadow-sm)]">
                <div className="px-4 sm:px-6 border-b border-[var(--border-soft)]">
                  <p className="text-sm font-semibold text-[var(--ink)] pt-4">
                    {showOptional ? t("grievanceWizard.optionalTab") : t("grievanceWizard.mandatoryTab")}
                  </p>
                  <div className="mt-3 flex flex-wrap gap-1.5 sm:gap-2 pb-4 overflow-x-auto">
                    {activeList.map((f, i) => {
                      const filled = (fieldAnswers[f.field] ?? "").trim().length > 0;
                      return (
                        <button
                          key={f.field}
                          type="button"
                          onClick={() => setActiveFieldIdx(i)}
                          className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-all ${
                            i === activeFieldIdx
                              ? "bg-[var(--accent-primary)] text-[var(--accent-contrast)] shadow-[var(--shadow-xs)]"
                              : filled
                                ? "bg-[var(--state-success)]/10 text-[var(--state-success)] ring-1 ring-[var(--state-success)]/30"
                                : "bg-[var(--cream)] text-[var(--ink)] hover:bg-[var(--cream-2)]"
                          }`}
                        >
                          {f.field_label || f.field.replace(/_/g, " ")}
                          {filled && <IconCheck className="h-3 w-3" />}
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div className="px-6 py-5">
                  <p className="text-xs font-semibold uppercase tracking-wide text-[var(--text-faint)]">
                    {t("grievanceWizard.fieldOf", { n: activeFieldIdx + 1, total: activeList.length })}
                  </p>

                  {activeField && (
                    <div className="mt-4">
                      <label className="mb-2 block text-sm font-medium text-[var(--text-primary)]">
                        {activeField.question}
                      </label>
                      {activeField.input_type === "text" && activeField.field.includes("description") ? (
                        <textarea
                          className="w-full rounded-[var(--radius-md)] border border-[var(--border-soft)] bg-[var(--surface-base)] p-3 text-sm text-[var(--ink)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)]"
                          rows={4}
                          value={fieldAnswers[activeField.field] ?? ""}
                          onChange={(e) => handleFieldChange(e.target.value)}
                        />
                      ) : (
                        <input
                          type={activeField.input_type === "date" ? "date" : "text"}
                          inputMode={activeField.input_type === "int" ? "numeric" : undefined}
                          pattern={activeField.input_type === "int" ? "[0-9]*" : undefined}
                          className="w-full rounded-[var(--radius-md)] border border-[var(--border-soft)] bg-[var(--surface-base)] p-3 text-sm text-[var(--ink)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)]"
                          value={fieldAnswers[activeField.field] ?? ""}
                          onChange={(e) => handleFieldChange(e.target.value)}
                        />
                      )}
                    </div>
                  )}
                </div>

                <div className="border-t border-[var(--border-soft)] px-4 sm:px-6 py-4">
                  <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
                    {showOptional ? (
                      <button
                        type="button"
                        onClick={() => { setShowOptional(false); setActiveFieldIdx(mandatoryFields.length - 1); }}
                        className="rounded-[var(--radius-md)] border border-[var(--border-soft)] px-4 py-2 text-sm font-medium text-[var(--ink)] transition-colors hover:bg-[var(--cream)]"
                      >
                        {t("grievanceWizard.backToMandatory")}
                      </button>
                    ) : (
                      <div />
                    )}

                    <div className="flex gap-3">
                      {!showOptional && activeFieldIdx < mandatoryFields.length - 1 && (
                        <button
                          type="button"
                          onClick={() => setActiveFieldIdx((i) => i + 1)}
                          className="inline-flex items-center gap-1.5 rounded-[var(--radius-md)] border border-[var(--border-soft)] px-4 py-2 text-sm font-medium text-[var(--ink)] transition-colors hover:bg-[var(--cream)]"
                        >
                          {t("common.next")}
                          <IconChevronRight className="h-3.5 w-3.5" />
                        </button>
                      )}
                      {showOptional && activeFieldIdx < optionalFields.length - 1 && (
                        <button
                          type="button"
                          onClick={() => setActiveFieldIdx((i) => i + 1)}
                          className="inline-flex items-center gap-1.5 rounded-[var(--radius-md)] border border-[var(--border-soft)] px-4 py-2 text-sm font-medium text-[var(--ink)] transition-colors hover:bg-[var(--cream)]"
                        >
                          {t("common.next")}
                          <IconChevronRight className="h-3.5 w-3.5" />
                        </button>
                      )}

                      {!showOptional && activeFieldIdx === mandatoryFields.length - 1 && (
                        <>
                          {optionalFields.length > 0 && (
                            <button
                              type="button"
                              onClick={() => { setShowOptional(true); setActiveFieldIdx(0); }}
                              disabled={fieldsBusy}
                              className="rounded-[var(--radius-md)] border border-[var(--border-soft)] px-4 py-2 text-sm font-medium text-[var(--ink)] transition-colors hover:bg-[var(--cream)] disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                              {t("grievanceWizard.addOptional")}
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={handleFieldsSubmit}
                            disabled={!mandatoryComplete || fieldsBusy}
                            className="inline-flex items-center gap-2 rounded-[var(--radius-cta)] bg-[var(--accent-primary)] px-5 py-2.5 text-sm font-semibold text-[var(--accent-contrast)] transition-colors hover:bg-[var(--accent-hover)] disabled:opacity-40 disabled:cursor-not-allowed"
                          >
                            {fieldsBusy ? (
                              <>
                                <span className="h-4 w-4 animate-spin rounded-full border-2 border-[var(--accent-contrast)]/30 border-t-[var(--accent-contrast)]" />
                                {t("grievanceWizard.submitting")}
                              </>
                            ) : (
                              <>
                                {t("grievanceWizard.submit")}
                                <IconChevronRight className="h-4 w-4" />
                              </>
                            )}
                          </button>
                        </>
                      )}

                      {showOptional && activeFieldIdx === optionalFields.length - 1 && (
                        <button
                          type="button"
                          onClick={handleFieldsSubmit}
                          disabled={!mandatoryComplete || fieldsBusy}
                          className="inline-flex items-center gap-2 rounded-[var(--radius-cta)] bg-[var(--accent-primary)] px-5 py-2.5 text-sm font-semibold text-[var(--accent-contrast)] transition-colors hover:bg-[var(--accent-hover)] disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                          {fieldsBusy ? (
                            <>
                              <span className="h-4 w-4 animate-spin rounded-full border-2 border-[var(--accent-contrast)]/30 border-t-[var(--accent-contrast)]" />
                              {t("grievanceWizard.submitting")}
                            </>
                          ) : (
                            <>
                              {t("grievanceWizard.submit")}
                              <IconChevronRight className="h-4 w-4" />
                            </>
                          )}
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* ── Step 4: Review ────────────────────────── */}
            {step === "review" && grievance && (
              <div className="rounded-[var(--radius-lg)] border border-[var(--border-soft)] bg-[var(--surface-elevated)] shadow-[var(--shadow-sm)]">
                <div className="flex items-center gap-3 border-b border-[var(--border-soft)] px-4 sm:px-6 py-4">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--state-success)]/10 text-[var(--state-success)]">
                    <IconCheck className="h-4 w-4" />
                  </span>
                  <div>
                    <p className="text-sm font-semibold text-[var(--ink)]">
                      {t("grievanceCard.ready")}
                    </p>
                    <p className="text-xs text-[var(--text-tertiary)]">
                      {grievance.reference}
                    </p>
                  </div>
                </div>

                <div className="px-4 sm:px-6 py-5 space-y-4">
                  <div>
                    <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-[var(--text-faint)]">
                      {t("grievanceCard.titleLabel")}
                    </p>
                    <p className="text-sm font-semibold text-[var(--ink)]">{grievance.title}</p>
                  </div>

                  <Divider />
                  <Row label={t("grievanceCard.category")} value={grievance.category} />
                  <Row label={t("grievanceCard.subCategory")} value={grievance.sub_category} />
                  <Row label={t("grievanceCard.department")} value={grievance.department} />
                  <Row label={t("grievanceCard.jurisdiction")} value={grievance.jurisdiction} />

                  {grievance.description?.display && (
                    <>
                      <Divider />
                      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-[var(--text-faint)]">
                        {t("grievanceCard.description")}
                      </p>
                      <p className="text-sm leading-relaxed text-[var(--ink)]">
                        {grievance.description.display}
                      </p>
                    </>
                  )}

                  {grievance.location && (grievance.location.ward_number || grievance.location.locality || grievance.location.area || grievance.location.city || grievance.location.state) && (
                    <>
                      <Divider />
                      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-[var(--text-faint)]">
                        {t("grievanceCard.location")}
                      </p>
                      <Row label={t("grievanceCard.wardNumber")} value={grievance.location.ward_number} />
                      <Row label={t("grievanceCard.locality")} value={grievance.location.locality} />
                      <Row label={t("grievanceCard.area")} value={grievance.location.area} />
                      <Row label={t("grievanceCard.city")} value={grievance.location.city} />
                      <Row label={t("grievanceCard.state")} value={grievance.location.state} />
                    </>
                  )}

                  {grievance.fields && Object.keys(grievance.fields).length > 0 && (
                    <>
                      <Divider />
                      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-[var(--text-faint)]">
                        {t("grievanceCard.fields")}
                      </p>
                      {Object.keys(grievance.fields).map((key) => {
                        const value = grievance.fields![key];
                        const camelKey = key.replace(/_([a-z])/g, (_, c: string) => c.toUpperCase());
                        const i18nKey = `field.${camelKey}` as Parameters<typeof t>[0];
                        const translated = t(i18nKey);
                        const label = translated !== i18nKey ? translated : key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
                        return <Row key={key} label={label} value={value} />;
                      })}
                    </>
                  )}

                  {grievance.submission && (grievance.submission.portal_name || grievance.submission.portal_url) && (
                    <>
                      <Divider />
                      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-[var(--text-faint)]">
                        {t("grievanceCard.submission")}
                      </p>
                      <Row label={t("grievanceCard.portal")} value={grievance.submission.portal_name} />
                      <Row label={t("grievanceCard.department")} value={grievance.submission.department} />
                      <Row label={t("grievanceCard.level")} value={grievance.submission.level} />

                      {grievance.submission.steps && grievance.submission.steps.length > 0 && (
                        <>
                          <Divider />
                          <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-[var(--text-faint)]">
                            {t("grievanceCard.steps")}
                          </p>
                          <ol className="list-decimal space-y-1.5 pl-5 text-sm text-[var(--ink)]">
                            {grievance.submission.steps.map((s, i) => (
                              <li key={i} className="leading-relaxed">{s}</li>
                            ))}
                          </ol>
                        </>
                      )}

                      {grievance.submission.required_documents && grievance.submission.required_documents.length > 0 && (
                        <>
                          <Divider />
                          <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-[var(--text-faint)]">
                            {t("grievanceCard.documents")}
                          </p>
                          <ul className="list-disc space-y-1 pl-5 text-sm text-[var(--ink)]">
                            {grievance.submission.required_documents.map((doc, i) => (
                              <li key={i} className="leading-relaxed">{doc}</li>
                            ))}
                          </ul>
                        </>
                      )}

                      {grievance.submission.estimated_timeline && (
                        <>
                          <Divider />
                          <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-[var(--text-faint)]">
                            {t("grievanceCard.timeline")}
                          </p>
                          <p className="text-sm font-medium text-[var(--ink)]">
                            {grievance.submission.estimated_timeline}
                          </p>
                        </>
                      )}

                      {grievance.submission.disclaimer && (
                        <>
                          <Divider />
                          <div className="flex items-start gap-2 rounded-[var(--radius-md)] bg-[var(--state-warning)]/10 px-3 py-2 text-xs text-[var(--state-warning)]">
                            <IconAlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                            <p>
                              <span className="font-semibold">{t("grievanceCard.disclaimer")}: </span>
                              {grievance.submission.disclaimer}
                            </p>
                          </div>
                        </>
                      )}
                    </>
                  )}
                </div>

                <div className="border-t border-[var(--border-soft)] px-4 sm:px-6 py-4">
                  <div className="flex justify-center">
                    <button
                      type="button"
                      onClick={startOver}
                      className="inline-flex items-center gap-2 rounded-[var(--radius-cta)] bg-[var(--accent-primary)] px-5 py-2.5 text-sm font-semibold text-[var(--accent-contrast)] transition-colors hover:bg-[var(--accent-hover)]"
                    >
                      {t("grievanceWizard.newComplaint")}
                      <IconChevronRight className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* ── Security Notice ──────────────────────────── */}
            <div className="mt-4 text-center">
              <p className="text-xs text-[var(--text-faint)]">
                <IconShield className="mr-1 inline h-3 w-3" />
                {t("grievanceWizard.draftWarning")}
              </p>
            </div>
          </div>

        {/* ── What Happens Next ───────────────────────────── */}
        <div className="mt-10 rounded-[var(--radius-lg)] border border-[var(--border-soft)] bg-[var(--surface-elevated)] p-4 shadow-[var(--shadow-sm)] sm:mt-12 sm:p-6">
          <div className="flex items-start gap-3">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--accent-primary)]/10 text-[var(--accent-primary)]">
              <IconInfo className="h-4 w-4" />
            </span>
            <div>
              <p className="text-sm font-semibold text-[var(--ink)]">
                {t("grievanceWizard.whatNext")}
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-[var(--text-tertiary)]">
                {["Review", "Route", "Track", "Resolve"].map((step, i) => (
                  <span key={step} className="inline-flex items-center gap-2">
                    <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-[var(--cream)] text-[10px] font-bold text-[var(--ink)]">
                      {i + 1}
                    </span>
                    {step}
                    {i < 3 && <span className="text-[var(--text-faint)]">→</span>}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Divider() {
  return <div className="border-t border-[var(--border-soft)]" />;
}

function Row({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) return null;
  return (
    <div className="flex items-start justify-between gap-3 py-1.5 text-sm">
      <span className="shrink-0 text-[var(--text-faint)]">{label}</span>
      <span className="text-right font-medium text-[var(--ink)]">{value}</span>
    </div>
  );
}
export { default as GrievancePage } from "./GrievancePage";
