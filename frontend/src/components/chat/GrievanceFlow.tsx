import { useState, useCallback, useMemo } from "react";
import { useI18n } from "@/lib/i18n/provider";
import type { ChatResponse } from "@/lib/api";
import { answerGrievanceField, finalizeGrievanceDraft, clarifyGrievance } from "@/lib/api";
import { GrievanceClassificationPanel } from "./GrievanceClassificationPanel";
import { GrievanceFieldPanel } from "./GrievanceFieldPanel";
import { GrievanceCard } from "./GrievanceCard";

interface GrievanceFlowProps {
  response: ChatResponse;
  onSendMessage: (message: string) => void;
  /** Called when the grievance is finalized. The callback receives the
   *  complete ChatResponse that should be persisted into the conversation
   *  history so the finalized card survives remount / refresh / reload. */
  onGrievanceFinalized?: (finalizedResponse: ChatResponse) => void;
  /** When true, this instance represents a HISTORICAL turn, not the live
   * one. Every classification table it holds is rendered permanently
   * read-only -- no button in a read-only instance can ever be clicked,
   * regardless of what happens in a later/newer instance. */
  readOnly?: boolean;
}

type DraftSummary = NonNullable<ChatResponse["grievance_draft_summary"]>;
type FieldsSchema = NonNullable<ChatResponse["grievance_fields_schema"]>;

interface ClassificationEntry {
  id: string;
  draft_summary: DraftSummary;
}

let entryCounter = 0;
function nextEntryId(): string {
  entryCounter += 1;
  return `classification-${Date.now()}-${entryCounter}`;
}

/**
 * GrievanceFlow orchestrates the structured grievance UI within the chat.
 *
 * It detects the grievance stage from the response metadata and renders
 * the appropriate UI component:
 * - "classification": Shows an append-only CHAIN of classification tables.
 *   Every "No, that's wrong" clarification produces a brand new table with
 *   its own id, appended BELOW the previous one. Earlier tables in the
 *   chain are never replaced, mutated, or removed -- they stay visible but
 *   become permanently read-only the moment a decision (Yes/No) is made on
 *   them, or the moment a newer table exists in the chain.
 * - "fields": Shows tabbed field collection UI (below the confirmed chain).
 * - "complete": Shows final grievance draft card (below the confirmed chain).
 *
 * When the user interacts with the UI, it sends the appropriate message
 * back through the chat flow.
 */
export function GrievanceFlow({ response, onSendMessage, onGrievanceFinalized, readOnly = false }: GrievanceFlowProps) {
  const { t, locale } = useI18n();
  const [isProcessing, setIsProcessing] = useState(false);
  const [isFinalizing, setIsFinalizing] = useState(false);

  // Append-only chain of classification tables for this grievance turn.
  // Seeded from whatever the server initially attached to this message.
  const initialEntries = useMemo<ClassificationEntry[]>(() => {
    if (response.grievance_stage === "classification" && response.grievance_draft_summary) {
      return [{ id: nextEntryId(), draft_summary: response.grievance_draft_summary }];
    }
    return [];
  }, [response]);
  const [classificationChain, setClassificationChain] = useState<ClassificationEntry[]>(initialEntries);

  // Once the user confirms (Yes) the LATEST table in the chain, the whole
  // chain becomes permanently read-only, and we move on to fields.
  const [chainConfirmed, setChainConfirmed] = useState(false);
  const [fieldsSchema] = useState<FieldsSchema | null>(
    response.grievance_stage === "fields" ? response.grievance_fields_schema ?? null : null,
  );
  const [fieldsDraftSummary] = useState<DraftSummary | null>(
    response.grievance_stage === "fields" ? response.grievance_draft_summary ?? null : null,
  );

  // Local state for finalized grievance - replaces response after finalization
  const [finalizedGrievance, setFinalizedGrievance] = useState<ChatResponse["grievance"]>(null);
  const [finalizedStage, setFinalizedStage] = useState<string | null>(null);

  // Detect already-finalized state from the response itself — handles
  // remount after navigation where local state is lost but the response
  // object (persisted in localStorage conversation history) still carries
  // the complete grievance with submission data.
  const responseIsFinalized =
    response.grievance_finalized === true ||
    (!!response.grievance && !!response.grievance.submission);

  const effectiveStage =
    finalizedStage ||
    (responseIsFinalized ? "complete" : chainConfirmed ? "fields" : "classification");
  const grievance = finalizedGrievance || response.grievance;
  const conversationId = response.conversation_id;
  const isFinalized = readOnly || response.grievance_finalized === true || finalizedGrievance !== null || responseIsFinalized;

  const handleConfirm = useCallback(() => {
    if (isFinalized) return;
    setIsProcessing(true);
    setChainConfirmed(true);
    onSendMessage("Yes, the information is correct");
  }, [onSendMessage, isFinalized]);

  const handleClarify = useCallback((clarification: string) => {
    if (isFinalized) return;
    setIsProcessing(true);
    // Use dedicated clarify endpoint - do NOT send through chat / the LLM.
    const doClarify = async () => {
      try {
        if (!conversationId) {
          console.error("No conversation ID for clarification");
          setIsProcessing(false);
          return;
        }
        const result = await clarifyGrievance({
          conversation_id: conversationId,
          complaint: clarification,
          language: locale || "en",
        });
        // Append a NEW, independent classification table to the chain.
        // The earlier table(s) are left untouched -- they simply stop being
        // the "latest" table and render read-only from now on.
        if (result.draft_summary) {
          setClassificationChain((prev) => [
            ...prev,
            { id: nextEntryId(), draft_summary: result.draft_summary as DraftSummary },
          ]);
        }
        setIsProcessing(false);
      } catch (error) {
        console.error("Failed to clarify grievance:", error);
        setIsProcessing(false);
      }
    };
    doClarify();
  }, [conversationId, locale, isFinalized]);

  const handleFieldSubmit = useCallback((answers: Record<string, string>) => {
    // Prevent double submission
    if (isFinalizing || isFinalized) return;

    setIsProcessing(true);
    setIsFinalizing(true);

    // Submit each field answer directly to the dedicated endpoint -- this
    // NEVER goes through /chat or the LLM. Values are stored verbatim.
    const submitFields = async () => {
      try {
        if (!conversationId) {
          console.error("No conversation ID for field submission");
          setIsProcessing(false);
          setIsFinalizing(false);
          return;
        }
        for (const [field, value] of Object.entries(answers)) {
          if (value.trim()) {
            await answerGrievanceField({
              conversation_id: conversationId,
              field,
              value: value.trim(),
            });
          }
        }
        const finalizeResult = await finalizeGrievanceDraft({
          conversation_id: conversationId,
          language: locale || "en",
        });
        // Store the finalized grievance locally - do NOT send through chat
        // This prevents old messages from overriding the current state
        setFinalizedGrievance(finalizeResult.grievance);
        setFinalizedStage("complete");
        setIsProcessing(false);
        // Note: isFinalizing stays true to keep the UI locked

        // Persist the finalized state into the conversation history so the
        // completed GrievanceCard survives remount / refresh / navigation.
        if (onGrievanceFinalized) {
          const finalizedResponse: ChatResponse = {
            ...response,
            grievance: finalizeResult.grievance,
            grievance_stage: "complete",
            grievance_finalized: true,
            speech_text: finalizeResult.speech_text || response.speech_text,
            speech_segments: finalizeResult.speech_segments?.length ? finalizeResult.speech_segments : response.speech_segments,
          };
          onGrievanceFinalized(finalizedResponse);
        }
      } catch (error) {
        console.error("Failed to submit grievance fields:", error);
        setIsProcessing(false);
        setIsFinalizing(false);
      }
    };
    submitFields();
  }, [conversationId, locale, isFinalizing, isFinalized]);

  const chainHasEntries = classificationChain.length > 0;
  const activeFieldsSchema = fieldsSchema || response.grievance_fields_schema;
  const activeFieldsDraftSummary = fieldsDraftSummary || response.grievance_draft_summary;
  const showFields =
    !responseIsFinalized &&
    !finalizedStage &&
    (chainConfirmed || response.grievance_stage === "fields") &&
    !!activeFieldsSchema;
  const showComplete = effectiveStage === "complete" && !!grievance;

  if (!chainHasEntries && !showFields && !showComplete) {
    // No structured grievance data - don't render anything
    return null;
  }

  return (
    <div className="space-y-3">
      {classificationChain.map((entry, idx) => {
        const isLastEntry = idx === classificationChain.length - 1;
        // Every table except the current, undecided, latest one is locked.
        // Once the chain is confirmed (moved on to fields) or the whole
        // grievance is finalized, ALL tables lock permanently.
        const entryLocked = readOnly || isFinalized || chainConfirmed || !isLastEntry;
        return (
          <GrievanceClassificationPanel
            key={entry.id}
            classification={entry.draft_summary}
            onConfirm={isLastEntry ? handleConfirm : () => {}}
            onClarify={isLastEntry ? handleClarify : () => {}}
            isFinalized={entryLocked}
            isBusy={isLastEntry && isProcessing}
          />
        );
      })}

      {showFields && activeFieldsSchema && activeFieldsDraftSummary && (
        <GrievanceFieldPanel
          fieldsSchema={activeFieldsSchema}
          draftSummary={activeFieldsDraftSummary}
          onSubmit={handleFieldSubmit}
          onCancel={() => onSendMessage("cancel")}
          isFinalized={readOnly || isFinalized}
          isSubmitting={isFinalizing}
        />
      )}

      {showComplete && grievance && (
        <div className="space-y-3">
          <GrievanceCard grievance={grievance} />
        </div>
      )}
    </div>
  );
}
