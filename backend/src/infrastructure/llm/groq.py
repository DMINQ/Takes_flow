"""
Groq adapter — transcript clean-up (filler words/hesitations/stutters removal).

Uses the official `groq` client with a strict, deterministic (temperature=0)
system prompt that instructs the model to act as a copy editor: strip
filler words and stutters without changing meaning, sentence structure or
punctuation, and without adding any conversational wrapper text.

Satisfies LLMPort. `similarity()` is not implemented by this adapter — bad-take
duplicate detection still runs on the fuzzy-match path (see
`application.pipeline.plugins.bad_take`); Groq here only cleans transcript text.
"""
from __future__ import annotations

from src.domain.errors import DomainError
from src.settings.config import LLMSettings


class LLMError(DomainError):
    """Raised when the Groq API call fails or returns an unusable response."""


class GroqLLM:
    """Adapter for LLM_PROVIDER=groq — transcript clean-up only."""

    def __init__(self, settings: LLMSettings) -> None:
        if not settings.groq_api_key:
            raise LLMError("LLM_GROQ_API_KEY is not set; cannot use LLM_PROVIDER=groq.")
        self._settings = settings

        from groq import Groq

        self._client = Groq(api_key=settings.groq_api_key)

    def similarity(self, a: str, b: str) -> float:
        raise NotImplementedError("GroqLLM only supports clean_transcript(); use the fuzzy bad-take path.")

    def clean_transcription(self, raw_text: str) -> str:
        """Alias kept for parity with the reference script; see `clean_transcript`."""
        return self.clean_transcript(raw_text)

    def clean_transcript(self, raw_text: str) -> str:
        if not raw_text.strip():
            return raw_text

        try:
            response = self._client.chat.completions.create(
                model=self._settings.groq_model,
                temperature=self._settings.groq_temperature,
                messages=[
                    {"role": "system", "content": self._settings.groq_system_prompt},
                    {"role": "user", "content": raw_text},
                ],
            )
        except Exception as exc:  # noqa: BLE001 - surface as a domain error
            raise LLMError(f"Groq API request failed: {exc}") from exc

        choices = getattr(response, "choices", None)
        if not choices:
            raise LLMError("Groq API returned no choices.")

        content = choices[0].message.content
        if content is None:
            raise LLMError("Groq API returned an empty message.")
        return content.strip()


if __name__ == "__main__":
    from src.settings.config import llm_settings

    llm = GroqLLM(llm_settings)
    original = "Ну, короче, э-э, я, м-э, думаю, что, ну, типа, это норм идея."
    cleaned = llm.clean_transcript(original)
    print("Original:", original)
    print("Cleaned:", cleaned)
