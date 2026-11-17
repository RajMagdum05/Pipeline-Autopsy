"""Deterministic Gemini substitute backed by approved synthetic recordings."""

import json
import os
from pathlib import Path
from types import SimpleNamespace


class FakeGemini:
    def __init__(self, recordings_path=None):
        path = Path(recordings_path or os.getenv("AUTOPSY_FAKE_GEMINI_RESULTS") or
                    Path(__file__).resolve().parents[2] / "demo_documents" /
                    "gemini_demo_results.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("synthetic_data_only") is not True:
            raise ValueError("FakeGemini recordings must be marked synthetic-only")
        self.documents = payload.get("documents", [])
        if not self.documents:
            raise ValueError("FakeGemini recordings contain no documents")
        self._counts = {document["filename"]: 0 for document in self.documents}
        self.models = _FakeModels(self)

    def _select_document(self, prompt):
        scored = []
        for document in self.documents:
            snippets = [
                line.strip() for page in document.get("page_text_sent_to_model", [])
                for line in str(page.get("text", "")).splitlines() if len(line.strip()) >= 8
            ]
            score = sum(1 for snippet in snippets if snippet.casefold() in prompt.casefold())
            scored.append((score, document))
        score, document = max(scored, key=lambda candidate: candidate[0])
        if score == 0:
            raise RuntimeError("FakeGemini could not match the request to a synthetic recording")
        return document

    def _generate(self, contents):
        document = self._select_document(str(contents))
        index = self._counts[document["filename"]]
        requests = document.get("gemini_requests", [])
        if index >= len(requests):
            raise RuntimeError("FakeGemini recording has no response for this request")
        self._counts[document["filename"]] += 1
        response = requests[index].get("model_structured_response")
        if not isinstance(response, dict):
            raise RuntimeError("FakeGemini recording response is not a JSON object")
        serialized = json.dumps(response, ensure_ascii=False)
        return SimpleNamespace(
            text=serialized,
            candidates=[SimpleNamespace(finish_reason="STOP")],
            usage_metadata=SimpleNamespace(
                prompt_token_count=max(1, len(str(contents)) // 4),
                candidates_token_count=max(1, len(serialized) // 4),
            ),
            model_version="recorded-synthetic",
        )


class _FakeModels:
    def __init__(self, fake):
        self._fake = fake

    def generate_content(self, *, contents, **_kwargs):
        return self._fake._generate(contents)


__all__ = ["FakeGemini"]
