
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from app.db import get_supabase

from .models import (
    GrievanceCategory,
    GrievanceDraft,
    GrievanceEntity,
    GrievanceStage,
    GrievanceState,
    GrievanceTurn,
    SubmissionRoute,
    StatusLookupResult,
)
from .classifier import GrievanceClassifier
from .draft_builder import GrievanceDraftBuilder, _looks_like_confirmation_or_unrelated
from .field_detector import GrievanceFieldDetector
from .followup_generator import GrievanceFollowupGenerator
from .submission_guide import GrievanceSubmissionGuide
from .status_lookup import GrievanceStatusLookup


def load_grievance_state(conversation_id: str) -> GrievanceState | None:
    """Load grievance state from Supabase. Return None on DB errors (e.g., test env)."""
    sb = get_supabase()
    try:
        result = (
            sb.table("grievance_states")
            .select("state_json")
            .eq("conversation_id", conversation_id)
            .limit(1)
            .execute()
        )
    except Exception:
        # DB unavailable – treat as no prior state
        return None
    rows = result.data or []
    if not rows:
        return None
    data = json.loads(rows[0]["state_json"])
    return GrievanceState.from_dict(data)


def save_grievance_state(state: GrievanceState) -> None:
    """Save grievance state to Supabase. Silently ignore DB errors in test env.

    Ownership gate (mirrors session_store.touch_session): when a row already
    exists for this conversation_id but is owned by someone else, the write
    is a no-op — never overwrite another owner's workflow.
    """
    state.updated_at = datetime.now(timezone.utc).isoformat()
    sb = get_supabase()
    try:
        existing = load_grievance_state(state.conversation_id)
    except Exception:
        existing = None
    if existing is not None and getattr(existing, "user_id", None) != state.user_id:
        return
    try:
        sb.table("grievance_states").upsert(
            {
                "conversation_id": state.conversation_id,
                "user_id": state.user_id,
                "state_json": json.dumps(state.to_dict(), ensure_ascii=False),
                "created_at": state.created_at,
                "updated_at": state.updated_at,
            },
            on_conflict="conversation_id",
        ).execute()
    except Exception:
        # In CI/tests Supabase may be unavailable; ignore.
        return


def _contains_word(text_lower: str, words: tuple[str, ...] | list[str]) -> bool:
    """Whole-word membership check.

    Plain substring checks (``"correct" in text``) wrongly match inside
    other words -- most importantly "incorrect" contains "correct", so a
    rejection like "the classification is incorrect" was being
    misdetected as a positive confirmation and the workflow skipped
    straight past reclassification. ``\\b`` word boundaries fix this for
    every word in the confirmation/rejection vocabularies, not just this
    one case.
    """
    return any(re.search(r"\b" + re.escape(word) + r"\b", text_lower) for word in words)


def _strip_matched_keywords(text: str, keywords: list[str]) -> str:
    """Remove previously-matched classification keywords from ``text``.

    Used when reclassifying a grievance after the citizen rejects the
    current classification: the OLD classification's own keywords tend
    to reappear in the rejection message purely as a negation (e.g. "I
    don't want to complain about garbage") and would otherwise bias the
    keyword-count classifier straight back into the rejected category.
    This is a generic string operation -- it doesn't hardcode any
    specific complaint category or type.
    """
    result = text
    for keyword in sorted(set(keywords), key=len, reverse=True):
        if not keyword:
            continue
        result = re.sub(re.escape(keyword), " ", result, flags=re.IGNORECASE)
    return result


@dataclass
class WorkflowResult:
    """Result of a workflow step."""

    response: str
    stage: GrievanceStage
    draft: GrievanceDraft | None
    is_complete: bool
    submission_route: SubmissionRoute | None = None
    status_lookup: StatusLookupResult | None = None
    evidence: list = None

    def __post_init__(self):
        if self.evidence is None:
            self.evidence = []


class GrievanceWorkflow:
    """Main grievance workflow orchestrator."""

    def __init__(self):
        self.classifier = GrievanceClassifier()
        self.draft_builder = GrievanceDraftBuilder()
        self.field_detector = GrievanceFieldDetector()
        self.followup_generator = GrievanceFollowupGenerator()
        self.submission_guide = GrievanceSubmissionGuide()
        self.status_lookup = GrievanceStatusLookup()

    def process_message(
        self,
        user_message: str,
        conversation_id: str,
        user_id: str,
    ) -> WorkflowResult:
        """Process a user message in the grievance workflow.

        Ownership: a stored state owned by someone else collapses to a
        fresh state for the caller — identical to no prior workflow, so
        one user's draft/fields are never visible to another. Combined
        with the save-gate below, a foreign caller can neither read nor
        overwrite another owner's workflow.
        """
        state = load_grievance_state(conversation_id)
        if state is None or getattr(state, "user_id", None) != user_id:
            state = GrievanceState(
                conversation_id=conversation_id,
                user_id=user_id,
            )

        # Defense: if a completed grievance is loaded, check whether the
        # incoming message looks like a NEW complaint (not just a
        # follow-up like "status" or "submit").  If so, start a fresh
        # intake so the new grievance gets its own reference number.
        if state.is_complete and state.stage in (
            GrievanceStage.COMPLETE,
            GrievanceStage.SUBMISSION_GUIDE,
            GrievanceStage.STATUS_LOOKUP,
            GrievanceStage.DRAFT_READY,
        ):
            user_lower = user_message.lower()
            is_followup = any(
                word in user_lower
                for word in ("status", "track", "check", "submit", "portal", "where")
            )
            is_explicit_new = any(
                phrase in user_lower
                for phrase in (
                    "new grievance", "another grievance", "file a new",
                    "start a new", "start over",
                )
            )
            classification = self.classifier.classify(user_message)
            has_problem_signal = any(
                indicator in user_lower
                for indicator in self._PROBLEM_INDICATORS
            )
            is_known_category = (
                classification.category != GrievanceCategory.OTHER
                and classification.confidence >= 0.5
            )
            if not is_followup and (is_explicit_new or has_problem_signal or is_known_category):
                state = GrievanceState(
                    conversation_id=conversation_id,
                    user_id=user_id,
                )

        turn_id = len(state.turns) + 1

        if state.stage == GrievanceStage.INTAKE:
            result = self._handle_intake(state, user_message, turn_id)
        elif state.stage == GrievanceStage.CLASSIFICATION:
            result = self._handle_classification(state, user_message, turn_id)
        elif state.stage == GrievanceStage.ENTITY_EXTRACTION:
            result = self._handle_entity_extraction(state, user_message, turn_id)
        elif state.stage == GrievanceStage.MISSING_FIELDS:
            result = self._handle_missing_fields(state, user_message, turn_id)
        elif state.stage == GrievanceStage.FOLLOWUP:
            result = self._handle_followup(state, user_message, turn_id)
        elif state.stage == GrievanceStage.DRAFT_READY:
            result = self._handle_draft_ready(state, user_message, turn_id)
        elif state.stage == GrievanceStage.SUBMISSION_GUIDE:
            result = self._handle_submission_guide(state, user_message, turn_id)
        elif state.stage == GrievanceStage.STATUS_LOOKUP:
            result = self._handle_status_lookup(state, user_message, turn_id)
        else:
            result = self._handle_complete(state, user_message, turn_id)

        turn = GrievanceTurn(
            turn_id=turn_id,
            user_message=user_message,
            assistant_message=result.response,
            stage=result.stage,
            extracted_entities=result.draft.entities if result.draft else {},
            asked_questions=self.followup_generator.generate_questions(
                result.draft, user_message
            ) if result.draft else [],
        )
        state.turns.append(turn)

        state.stage = result.stage
        state.draft = result.draft
        state.is_complete = result.is_complete
        state.updated_at = datetime.now(timezone.utc).isoformat()

        save_grievance_state(state)

        return result

    def _handle_intake(
        self,
        state: GrievanceState,
        user_message: str,
        turn_id: int,
    ) -> WorkflowResult:
        """Handle initial complaint intake."""
        classification = self.classifier.classify(user_message)

        if classification.category.value == "other" and classification.confidence < 0.4:
            return WorkflowResult(
                response=(
                    "I understand you want to file a grievance. Could you please "
                    "describe your complaint or problem in more detail? For example:\n"
                    "- What happened?\n"
                    "- Which government department or service is involved?\n"
                    "- When did it happen?\n"
                    "- What is the impact on you?"
                ),
                stage=GrievanceStage.INTAKE,
                draft=None,
                is_complete=False,
            )

        draft = self.draft_builder.build_initial_draft(
            user_message, state.conversation_id, state.user_id
        )
        state.draft = draft

        state.stage = GrievanceStage.CLASSIFICATION

        response = self._format_classification_confirmation(draft, classification)

        return WorkflowResult(
            response=response,
            stage=GrievanceStage.CLASSIFICATION,
            draft=draft,
            is_complete=False,
        )

    def _handle_classification(
        self,
        state: GrievanceState,
        user_message: str,
        turn_id: int,
    ) -> WorkflowResult:
        """Handle classification confirmation."""
        draft = state.draft

        user_lower = user_message.lower()

        # e.g. "incorrect" must NOT match "correct".
        if _contains_word(user_lower, ["yes", "correct", "right", "confirm", "ok", "proceed", "continue"]):
            state.stage = GrievanceStage.ENTITY_EXTRACTION
            return self._handle_entity_extraction(state, user_message, turn_id)

        if _contains_word(user_lower, ["no", "wrong", "incorrect", "not", "different", "change"]):
            original_complaint = draft.description if draft else user_message

            old_classification = self.classifier.classify(original_complaint)
            correction_only = _strip_matched_keywords(user_message, old_classification.matched_keywords)
            correction_classification = self.classifier.classify(correction_only)

            if correction_classification.category != GrievanceCategory.OTHER:
                reclassification_text = correction_only
                classification = correction_classification
            else:
                stripped_original = _strip_matched_keywords(
                    original_complaint, old_classification.matched_keywords
                )
                reclassification_text = f"{stripped_original} {correction_only}".strip()
                classification = self.classifier.classify(reclassification_text)

            if classification.category == GrievanceCategory.OTHER:
                # with no extractable corrected complaint. Do NOT guess --
                return WorkflowResult(
                    response=(
                        "No problem. Could you describe what your complaint is "
                        "actually about, so I can classify it correctly?"
                    ),
                    stage=GrievanceStage.CLASSIFICATION,
                    draft=draft,
                    is_complete=False,
                )

            # sub-category/title/department/fields do not linger.
            new_draft = self.draft_builder.build_initial_draft(
                reclassification_text, state.conversation_id, state.user_id
            )
            if draft is not None and draft.reference_number:
                new_draft.reference_number = draft.reference_number
            new_draft.description = user_message.strip() or original_complaint
            draft = new_draft
            state.draft = draft
            state.current_field = None

            # IMPORTANT: a clarification (NO + new description) must produce a
            # brand new, independent CLASSIFICATION result -- not skip ahead
            # into entity extraction. The citizen must explicitly confirm the
            # *new* classification (YES/NO) before the workflow advances, the
            # same way the very first classification requires confirmation.
            # Returning ENTITY_EXTRACTION here previously caused the new
            # classification table to be skipped/merged into the old one.
            state.stage = GrievanceStage.CLASSIFICATION

            response = self._format_classification_confirmation(draft, classification)

            return WorkflowResult(
                response=response,
                stage=GrievanceStage.CLASSIFICATION,
                draft=draft,
                is_complete=False,
            )

        return WorkflowResult(
            response=(
                "Please confirm if the classification is correct, or describe your "
                "complaint differently so I can classify it properly."
            ),
            stage=GrievanceStage.CLASSIFICATION,
            draft=draft,
            is_complete=False,
        )

    def _handle_entity_extraction(
        self,
        state: GrievanceState,
        user_message: str,
        turn_id: int,
    ) -> WorkflowResult:
        """Handle entity extraction from user message."""
        draft = state.draft

        draft = self.draft_builder.update_draft(draft, user_message)
        state.draft = draft

        missing_required, _missing_optional = self.field_detector.detect_missing_fields(
            draft, user_message
        )

        if missing_required:
            state.stage = GrievanceStage.FOLLOWUP
            next_field = missing_required[0]
            state.current_field = next_field
            question = self.followup_generator.generate_single_question(draft, user_message)
            state.pending_questions = [question] if question else []
            state.current_question_index = 0

            response = self.followup_generator.format_questions_response(
                state.pending_questions
            )
            response = (
                "Thank you. I've updated your grievance draft.\n\n"
                + self.draft_builder.format_draft_for_display(draft)
                + "\n\n" + response
            )

            return WorkflowResult(
                response=response,
                stage=GrievanceStage.FOLLOWUP,
                draft=draft,
                is_complete=False,
            )
        else:
            state.current_field = None
            state.stage = GrievanceStage.DRAFT_READY
            return self._handle_draft_ready(state, user_message, turn_id)

    def _handle_missing_fields(
        self,
        state: GrievanceState,
        user_message: str,
        turn_id: int,
    ) -> WorkflowResult:
        """Handle missing fields detection."""
        return self._handle_entity_extraction(state, user_message, turn_id)

    def _handle_followup(
        self,
        state: GrievanceState,
        user_message: str,
        turn_id: int,
    ) -> WorkflowResult:
        """Handle follow-up question responses."""
        draft = state.draft
        target_field = state.current_field

        user_lower = user_message.lower()
        if any(phrase in user_lower for phrase in ["new grievance", "another grievance", "file a new", "start a new", "start over"]):
            new_state = GrievanceState(
                conversation_id=state.conversation_id,
                user_id=state.user_id,
            )
            save_grievance_state(new_state)
            return self._handle_intake(new_state, user_message, 1)

        if target_field and _looks_like_confirmation_or_unrelated(user_message) and \
                user_message.strip().endswith("?"):
            prompt = self.field_detector.get_field_prompts(draft.sub_category).get(
                target_field, f"Please provide {target_field.replace('_', ' ')}."
            )
            response = (
                "That looks like a separate question, unrelated to your grievance. "
                "I'm not able to answer general questions here, but let's continue "
                "with your grievance first.\n\n"
                f"❓ {prompt}"
            )
            return WorkflowResult(
                response=response,
                stage=GrievanceStage.FOLLOWUP,
                draft=draft,
                is_complete=False,
            )

        correction_field = self._detect_correction_target(user_message, draft, target_field)
        if correction_field:
            semantic_result = self.draft_builder.semantic_extractor.extract(
                current_field=correction_field,
                user_message=user_message,
                known_fields=set(draft.entities.keys()),
                required_fields=draft.required_fields,
                optional_fields=draft.optional_fields,
                missing_fields=draft.missing_fields,
                original_complaint=draft.description,
                category=draft.category.value,
                sub_category=draft.sub_category.value,
                department=draft.department,
            )
            new_value = semantic_result.extracted_fields.get(correction_field)
            if not new_value:
                stripped = user_message.strip()
                for cue in self._CORRECTION_CUES:
                    idx = stripped.lower().find(cue.strip())
                    if idx != -1:
                        stripped = stripped[idx + len(cue):].strip(" ,")
                        break
                new_value = stripped or user_message.strip()

            draft.entities[correction_field] = GrievanceEntity(
                name=correction_field,
                value=new_value,
                confidence=0.8,
                source_text=user_message[:200],
            )
            _, _ = self.field_detector.detect_missing_fields(draft, "")
            missing_required, _ = self.field_detector.detect_missing_fields(draft, "")
            draft.missing_fields = missing_required
            state.draft = draft

            if missing_required:
                prompt = self.field_detector.get_field_prompts(draft.sub_category).get(
                    state.current_field, f"Please provide {state.current_field.replace('_', ' ')}."
                ) if state.current_field else None
                response = (
                    f"Got it, I've updated **{correction_field.replace('_', ' ').title()}**.\n\n"
                    + self.draft_builder.format_draft_for_display(draft)
                )
                if prompt:
                    response += f"\n\n❓ {prompt}"
                return WorkflowResult(
                    response=response,
                    stage=GrievanceStage.FOLLOWUP,
                    draft=draft,
                    is_complete=False,
                )
            else:
                state.current_field = None
                state.stage = GrievanceStage.DRAFT_READY
                return self._handle_draft_ready(state, user_message, turn_id)

        draft = self.draft_builder.update_draft(draft, user_message, target_field=target_field)
        state.draft = draft

        missing_required, _ = self.field_detector.detect_missing_fields(draft, user_message)

        if missing_required:
            next_field = missing_required[0]
            state.current_field = next_field
            question = self.followup_generator.generate_single_question(draft, user_message)
            state.pending_questions = [question] if question else []
            response = self.followup_generator.format_questions_response(
                state.pending_questions
            )
            response = (
                "Thank you. I've updated your information.\n\n"
                + self.draft_builder.format_draft_for_display(draft)
                + "\n\n" + response
            )

            return WorkflowResult(
                response=response,
                stage=GrievanceStage.FOLLOWUP,
                draft=draft,
                is_complete=False,
            )
        else:
            state.current_field = None
            state.stage = GrievanceStage.DRAFT_READY
            return self._handle_draft_ready(state, user_message, turn_id)

    _CORRECTION_CUES = (
        "correction", "correct that", "actually", "i meant", "sorry i meant",
        "change that to", "not ", "instead of", "wrong, ", "that's wrong",
    )

    def _detect_correction_target(
        self,
        user_message: str,
        draft: GrievanceDraft,
        currently_asked_field: str | None = None,
    ) -> str | None:
        """
        Detect whether the user is correcting a field they already
        answered (as opposed to answering the field currently being
        asked). Returns the entity key to correct, or None.

        This only ever matches against fields that already have a value
        in ``draft.entities`` -- it never invents a new field -- and only
        fires when the message contains an explicit correction cue, so an
        ordinary answer to the current question is never mistaken for a
        correction.
        """
        text_lower = user_message.lower()
        if not any(cue in text_lower for cue in self._CORRECTION_CUES):
            return None

        if not draft.entities:
            return None

        best_match = None
        best_overlap = 0
        for key in draft.entities:
            tokens = [t for t in key.split("_") if len(t) > 2]
            overlap = sum(1 for t in tokens if t in text_lower)
            if overlap > best_overlap:
                best_overlap = overlap
                best_match = key

        if best_match:
            return best_match

        if currently_asked_field and currently_asked_field in draft.entities:
            return currently_asked_field
        return None

    def _handle_draft_ready(
        self,
        state: GrievanceState,
        user_message: str,
        turn_id: int,
    ) -> WorkflowResult:
        """Handle when draft is complete."""
        draft = state.draft

        submission_route = self.submission_guide.get_submission_route(draft)

        state.stage = GrievanceStage.SUBMISSION_GUIDE
        state.is_complete = True

        response = (
            "✅ **Your grievance draft is complete!**\n\n"
            + self.draft_builder.format_draft_for_display(draft)
            + "\n\n"
            + self.submission_guide.format_route_for_display(submission_route)
        )

        return WorkflowResult(
            response=response,
            stage=GrievanceStage.SUBMISSION_GUIDE,
            draft=draft,
            is_complete=True,
            submission_route=submission_route,
        )

    def _handle_submission_guide(
        self,
        state: GrievanceState,
        user_message: str,
        turn_id: int,
    ) -> WorkflowResult:
        """Handle submission guide - offer status lookup."""
        draft = state.draft

        user_lower = user_message.lower()
        if any(word in user_lower for word in ["status", "track", "check", "lookup"]):
            state.stage = GrievanceStage.STATUS_LOOKUP
            return self._handle_status_lookup(state, user_message, turn_id)

        # to start a *new* grievance here must start clean, the same way
        if any(phrase in user_lower for phrase in ["new grievance", "another grievance", "file a new", "start a new", "start over"]):
            new_state = GrievanceState(
                conversation_id=state.conversation_id,
                user_id=state.user_id,
            )
            save_grievance_state(new_state)
            return self._handle_intake(new_state, user_message, 1)

        if any(word in user_lower for word in ["change", "modify", "edit", "update", "add"]):
            state.stage = GrievanceStage.ENTITY_EXTRACTION
            return self._handle_entity_extraction(state, user_message, turn_id)

        # Detect substantive new complaints that don't use explicit "new grievance"
        # keywords.  If the message looks like a fresh problem report (contains
        # grievance-related keywords or classifies as a known category), start a
        # new grievance flow instead of looping on the submission guide.
        has_problem_signal = any(
            indicator in user_lower for indicator in self._PROBLEM_INDICATORS
        )
        classification = self.classifier.classify(user_message)
        is_known_category = classification.category != GrievanceCategory.OTHER and classification.confidence >= 0.5
        if has_problem_signal or is_known_category:
            new_state = GrievanceState(
                conversation_id=state.conversation_id,
                user_id=state.user_id,
            )
            save_grievance_state(new_state)
            return self._handle_intake(new_state, user_message, 1)

        status_lookup = self.status_lookup.get_status_lookup(draft)
        response = (
            "You now have a complete grievance draft and know where to submit it.\n\n"
            "Would you like guidance on how to check the status of your grievance "
            "after you submit it?\n\n"
            + self.status_lookup.format_lookup_for_display(status_lookup)
        )

        return WorkflowResult(
            response=response,
            stage=GrievanceStage.SUBMISSION_GUIDE,
            draft=draft,
            is_complete=True,
            status_lookup=status_lookup,
        )

    def _handle_status_lookup(
        self,
        state: GrievanceState,
        user_message: str,
        turn_id: int,
    ) -> WorkflowResult:
        """Handle status lookup guidance."""
        draft = state.draft
        status_lookup = self.status_lookup.get_status_lookup(draft)

        state.stage = GrievanceStage.COMPLETE
        state.is_complete = True

        response = (
            "Here's how you can track your grievance status after submission:\n\n"
            + self.status_lookup.format_lookup_for_display(status_lookup)
            + "\n\n"
            "**Your reference number:** " + (draft.reference_number or "N/A") + "\n"
            "Save this number for future reference.\n\n"
            "Is there anything else I can help you with regarding this grievance?"
        )

        return WorkflowResult(
            response=response,
            stage=GrievanceStage.COMPLETE,
            draft=draft,
            is_complete=True,
            status_lookup=status_lookup,
        )

    def _handle_complete(
        self,
        state: GrievanceState,
        user_message: str,
        turn_id: int,
    ) -> WorkflowResult:
        """Handle conversation after completion."""
        draft = state.draft
        user_lower = user_message.lower()

        if any(word in user_lower for word in ["status", "track", "check"]):
            status_lookup = self.status_lookup.get_status_lookup(draft)
            return WorkflowResult(
                response=self.status_lookup.format_lookup_for_display(status_lookup),
                stage=GrievanceStage.STATUS_LOOKUP,
                draft=draft,
                is_complete=True,
                status_lookup=status_lookup,
            )

        if any(word in user_lower for word in ["submit", "portal", "where"]):
            submission_route = self.submission_guide.get_submission_route(draft, language="en")
            return WorkflowResult(
                response=self.submission_guide.format_route_for_display(submission_route),
                stage=GrievanceStage.SUBMISSION_GUIDE,
                draft=draft,
                is_complete=True,
                submission_route=submission_route,
            )

        if any(word in user_lower for word in ["change", "modify", "new", "another"]):
            new_state = GrievanceState(
                conversation_id=state.conversation_id,
                user_id=state.user_id,
            )
            save_grievance_state(new_state)
            return self._handle_intake(new_state, user_message, 1)

        return WorkflowResult(
            response=(
                "Your grievance workflow is complete. You have:\n"
                f"1. A structured draft (Ref: {draft.reference_number})\n"
                "2. Official submission route guidance\n"
                "3. Status lookup guidance\n\n"
                "You can ask me about status tracking, submission details, "
                "or start a new grievance."
            ),
            stage=GrievanceStage.COMPLETE,
            draft=draft,
            is_complete=True,
        )

    def _format_classification_confirmation(
        self,
        draft: GrievanceDraft,
        classification,
    ) -> str:
        """Format classification confirmation message."""
        return (
            f"I've analyzed your complaint and classified it as:\n\n"
            f"**Category:** {draft.category.value.replace('_', ' ').title()}\n"
            f"**Sub-category:** {draft.sub_category.value.replace('_', ' ').title()}\n"
            f"**Department:** {draft.department}\n"
            f"**Confidence:** {classification.confidence:.0%}\n\n"
            f"**Draft Title:** {draft.title}\n\n"
            f"Is this classification correct? If yes, I'll help you provide "
            f"the required details. If not, please describe your complaint differently."
        )

    _PROBLEM_INDICATORS = (
        "pending", "delay", "delayed", "not received", "haven't received",
        "has not been", "has not", "hasn't been", "hasn't", "not credited", "not credited yet",
        "rejected", "denied", "refused", "refusing", "refuse",
        "complain", "complaint", "grievance", "wrong", "incorrect",
        "harassment", "harassed", "corruption", "bribe", "misuse",
        "cheated", "fraud", "shortage", "overcharge", "over charged",
        "not working", "stopped", "no response", "ignored", "ignoring",
        "dispute", "issue with", "problem with", "not processed",
        "still waiting", "no action", "inaction", "not resolved",
        "escalate", "escalation", "status of my", "check my status",
        "sanitation", "dirty", "filth", "unclean", "litter",
        "report a", "reporting a", "report the", "report this",
    )

    _INFORMATIONAL_RE = re.compile(
        r"^(?:what|who|where|when|why|how|which|whose|tell|show|list|give|explain|define|name|describe|is|are|was|were|do|does|did|can|could|would|should)\b",
    )

    # Categories that are inherently informational — people ask about
    # them without necessarily filing a complaint.  A match in these
    # categories alone does NOT mean the query is a grievance.
    _INFORMATIONAL_CATEGORIES = frozenset({
        GrievanceCategory.COOPERATIVE,
        GrievanceCategory.AGRICULTURE,
        GrievanceCategory.BANKING,
        GrievanceCategory.SOCIAL_WELFARE,
        GrievanceCategory.EDUCATION,
        GrievanceCategory.REVENUE,
    })

    def is_grievance_query(self, text: str) -> bool:
        """Quick check if text is likely a grievance query."""
        text_lower = text.lower().strip()

        has_problem_signal = any(
            indicator in text_lower for indicator in self._PROBLEM_INDICATORS
        )

        looks_informational = bool(self._INFORMATIONAL_RE.match(text_lower))

        if looks_informational and not has_problem_signal:
            return False

        classification = self.classifier.classify(text)

        # If classifier assigns a specific category (not OTHER), treat as
        # grievance — UNLESS the category is inherently informational
        # (e.g. COOPERATIVE, AGRICULTURE) and there are no explicit
        # problem signals.  A cooperative-related query about rules or
        # regulations is NOT a grievance; "garbage piling up" IS.
        if classification.category != GrievanceCategory.OTHER:
            if classification.category in self._INFORMATIONAL_CATEGORIES and not has_problem_signal:
                return False
            return True

        # Fallback: rely on problem signals.
        return has_problem_signal
