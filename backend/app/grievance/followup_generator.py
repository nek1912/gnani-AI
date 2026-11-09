
from __future__ import annotations


from .models import GrievanceDraft
from .field_detector import GrievanceFieldDetector
from .translations import translate_grievance_string, FIELD_PROMPTS


class GrievanceFollowupGenerator:
    """Generates follow-up questions for missing grievance fields."""

    def __init__(self):
        self.field_detector = GrievanceFieldDetector()

    def generate_questions(
        self,
        draft: GrievanceDraft,
        user_message: str = "",
        max_questions: int = 3,
        lang: str = "en",
    ) -> list[str]:
        """Generate follow-up questions for missing fields."""
        missing_required, missing_optional = self.field_detector.detect_missing_fields(
            draft, user_message
        )

        questions = []
        prompts = self.field_detector.get_field_prompts(draft.sub_category)

        for field in missing_required:
            if len(questions) >= max_questions:
                break
            prompt = prompts.get(field, f"Please provide {field.replace('_', ' ')}.")
            if lang != "en":
                translated = FIELD_PROMPTS.get(prompt, {}).get(lang)
                if translated:
                    prompt = translated
            questions.append(prompt)

        for field in missing_optional:
            if len(questions) >= max_questions:
                break
            prompt = prompts.get(field, f"Please provide {field.replace('_', ' ')} (optional).")
            if lang != "en":
                translated = FIELD_PROMPTS.get(prompt, {}).get(lang)
                if translated:
                    prompt = translated
            questions.append(prompt + " (optional)" if lang == "en" else prompt + (" (वैकल्पिक)" if lang == "hi" else ""))

        return questions

    def generate_single_question(
        self,
        draft: GrievanceDraft,
        user_message: str = "",
        lang: str = "en",
    ) -> str | None:
        """Generate a single follow-up question."""
        questions = self.generate_questions(draft, user_message, max_questions=1, lang=lang)
        return questions[0] if questions else None

    def format_questions_response(
        self,
        questions: list[str],
        stage: str = "followup",
        lang: str = "en",
    ) -> str:
        """Format questions into a user-friendly response."""
        if not questions:
            return ""

        single_prefix = "To help you better, I need one more detail:\n\n"
        multi_prefix = "To complete your grievance draft, I need a few more details:\n\n"
        suffix = "You can answer them one by one or provide multiple details at once."

        if lang != "en":
            single_prefix = translate_grievance_string(single_prefix, lang, "followup_prefix") or single_prefix
            multi_prefix = translate_grievance_string(multi_prefix, lang, "followup_prefix") or multi_prefix
            suffix = translate_grievance_string(suffix, lang, "followup_prefix") or suffix

        if len(questions) == 1:
            return (
                single_prefix
                + f"\u2753 {questions[0]}"
            )

        response = multi_prefix
        for i, q in enumerate(questions, 1):
            response += f"{i}. {q}\n\n"

        response += suffix
        return response
