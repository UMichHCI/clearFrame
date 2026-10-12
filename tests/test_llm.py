import unittest
from unittest.mock import Mock

from openai.types.chat import ChatCompletion

from clearframe.config import MODEL_FULL, MODEL_MINI
from clearframe.llm import api_chat


class ModelMigrationTests(unittest.TestCase):
    def client(self, model=MODEL_FULL, content=' {"ok": true} ', finish_reason="stop", refusal=None):
        client = Mock()
        client.chat.completions.create.return_value = ChatCompletion.model_validate({
            "id": "test-completion", "object": "chat.completion", "created": 0,
            "model": model,
            "choices": [{
                "index": 0, "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": content, "refusal": refusal},
            }],
        })
        return client

    def test_analysis_uses_sol_with_medium_reasoning_and_json(self):
        client = self.client()
        answer = api_chat(client, "Return JSON.", "Analyze this article.",
                          model=MODEL_FULL, max_tokens=4500,
                          response_format={"type": "json_object"})
        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-6.1-sol")
        self.assertEqual(kwargs["reasoning_effort"], "medium")
        self.assertEqual(kwargs["max_completion_tokens"], 29500)
        self.assertNotIn("max_tokens", kwargs)
        self.assertEqual(kwargs["response_format"], {"type": "json_object"})
        self.assertEqual(answer, '{"ok": true}')

    def test_default_tasks_use_luna_with_low_reasoning(self):
        client = self.client(model=MODEL_MINI)
        api_chat(client, "Return JSON.", "Make a query plan.", max_tokens=700)
        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-6-luna")
        self.assertEqual(kwargs["reasoning_effort"], "low")
        self.assertEqual(kwargs["max_completion_tokens"], 4796)
        self.assertNotIn("max_tokens", kwargs)

    def test_truncated_output_is_rejected_before_json_parsing(self):
        client = self.client(content='{"partial":', finish_reason="length")
        with self.assertRaisesRegex(RuntimeError, "finish_reason=length"):
            api_chat(client, "Return JSON.", "Analyze.", model=MODEL_FULL)
        client.chat.completions.create.assert_called_once()

    def test_empty_or_refused_output_has_a_clear_error(self):
        for content, refusal, message in (
            (None, None, "empty response"),
            (" ", None, "empty response"),
            (None, "Refused", "refused"),
        ):
            with self.subTest(content=content, refusal=refusal):
                client = self.client(content=content, refusal=refusal)
                with self.assertRaisesRegex(RuntimeError, message):
                    api_chat(client, "Return JSON.", "Analyze.", model=MODEL_FULL)


if __name__ == "__main__":
    unittest.main()
