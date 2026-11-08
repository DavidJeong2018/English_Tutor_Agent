"""Translates English to Korean and explains phrases using the Claude API."""
from __future__ import annotations

from collections import OrderedDict
from typing import List

import anthropic
from pydantic import BaseModel, Field

SYSTEM_PROMPT = """\
You are an English tutor for native Korean speakers who are reading English \
documents. The user highlighted some English text. Respond in natural, fluent \
Korean (한국어) except where a field asks for English.

- translation: translate the whole text into natural Korean, keeping the meaning \
and tone. Do not translate word by word.
- phrases: idioms, phrasal verbs, collocations, or expressions in the text whose \
meaning is not obvious from the individual words. Explain each one in Korean and \
give one short, new English example sentence. Return an empty list if there are none.
- vocabulary: up to 6 words from the text that an intermediate Korean learner may \
not know (skip basic words). Give the dictionary form, part of speech, the Korean \
meaning that fits this context, and a short English example sentence.
If the text is a single word or phrase, the translation is its Korean meaning in context."""


class Phrase(BaseModel):
    phrase: str = Field(description="The phrase exactly as it appears in the text")
    meaning_ko: str = Field(description="Short Korean meaning")
    explanation_ko: str = Field(description="Korean explanation of usage and nuance")
    example_en: str = Field(description="A new English example sentence")


class Word(BaseModel):
    word: str = Field(description="Dictionary form of the word")
    part_of_speech: str = Field(description="e.g. noun, verb, adjective")
    meaning_ko: str = Field(description="Korean meaning in this context")
    example_en: str = Field(description="A short English example sentence")


class TutorResult(BaseModel):
    translation: str
    phrases: List[Phrase]
    vocabulary: List[Word]


OUTPUT_FORMAT = {"type": "json_schema", "schema": anthropic.transform_schema(TutorResult)}


class TranslationError(Exception):
    pass


class Translator:
    def __init__(self, api_key: str = "", model: str = "claude-opus-5-5", effort: str = "low"):
        # An empty key lets the SDK find ANTHROPIC_API_KEY or an `ant auth login` profile.
        self._client = anthropic.Anthropic(api_key=api_key or None, timeout=60.0)
        self.model = model
        self.effort = effort
        self._cache: "OrderedDict[str, TutorResult]" = OrderedDict()

    def explain(self, text: str) -> TutorResult:
        if text in self._cache:
            self._cache.move_to_end(text)
            return self._cache[text]
        try:
            response = self._client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                output_config={"effort": self.effort, "format": OUTPUT_FORMAT},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                messages=[{"role": "user", "content": text}],
            )
        except anthropic.AuthenticationError:
            raise TranslationError("API 키가 올바르지 않습니다. 설정에서 Anthropic API 키를 확인하세요.")
        except anthropic.RateLimitError:
            raise TranslationError("요청이 너무 많습니다. 잠시 후 다시 시도하세요.")
        except anthropic.APIConnectionError:
            raise TranslationError("인터넷 연결을 확인하세요.")
        except anthropic.APIStatusError as e:
            raise TranslationError(f"API 오류 ({e.status_code}): {e.message}")

        if response.stop_reason == "refusal":
            raise TranslationError("이 텍스트는 번역할 수 없습니다.")
        text_out = "".join(b.text for b in response.content if b.type == "text")
        try:
            result = TutorResult.model_validate_json(text_out)
        except ValueError:
            raise TranslationError("번역 결과를 읽을 수 없습니다. 다시 시도하세요.")

        self._cache[text] = result
        if len(self._cache) > 200:
            self._cache.popitem(last=False)
        return result
