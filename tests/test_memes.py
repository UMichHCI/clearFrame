import json
from pathlib import Path
import queue
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import httpx
from openai import RateLimitError

import app
from clearframe.memes import (CATALOG, STYLE_EXAMPLES, TEMPLATES, generate_meme_view,
                              prepare_meme_input, validate_generated_response, validate_meme_view)


RESULTS = {
    "summary": "The article emphasizes domestic costs over civilian harm.",
    "categories": [{"key": "agency_attribution", "label": "Who gets blamed", "paragraph": "The articles explain blame differently.",
                    "supporting_articles": [{"title": "Comparison", "url": "https://example.org", "source_country": "Oman"}]}],
}


def response_for(data=RESULTS):
    return {"items": [
        {"id": item["id"], "template_id": "drake", "captions": {"rejected": "The missing context", "preferred": "The familiar explanation"},
         "sentence": "The article emphasizes one explanation while giving another less attention.", "alt_text": "Drake rejects missing context and approves the familiar explanation."}
        for item in prepare_meme_input(data)["items"]
    ]}


def final_response_for(data=RESULTS):
    response = response_for(data)
    for item in response["items"]:
        item["fit_note"] = "Drake's rejected and preferred options express the difference in attention."
        item["checks"] = {key: True for key in ("grounded", "mechanism_fits", "clear_without_report", "plain_language", "distinct")}
    return response


class MemeGenerationTests(unittest.TestCase):
    def test_catalog_has_all_nine_supplied_images_and_bounded_caption_areas(self):
        self.assertEqual(len(TEMPLATES), 9)
        folder = Path(__file__).resolve().parent.parent / "static" / "meme-templates"
        for template in CATALOG["templates"]:
            self.assertTrue((folder / template["file"]).read_bytes().startswith(b"\xff\xd8"))
            self.assertTrue(template["description"])
            for slot in template["slots"]:
                x, y, width, height = slot["box"]
                self.assertGreater(width, 0)
                self.assertGreater(height, 0)
                self.assertGreaterEqual(x, 0)
                self.assertGreaterEqual(y, 0)
                self.assertLessEqual(round(x + width, 5), 1)
                self.assertLessEqual(round(y + height, 5), 1)

    @patch("clearframe.memes.api_chat")
    def test_one_text_only_call_covers_overview_and_findings(self, chat):
        data = {**RESULTS, "api_key": "private-key", "article_text": "raw-private-body", "llm_analysis": {"secret": "raw-private-details"}}
        chat.return_value = json.dumps(final_response_for())
        view = generate_meme_view(data, Mock())
        self.assertEqual([item["id"] for item in view["items"]], ["overview", "finding-1"])
        self.assertEqual(view["version"], 2)
        self.assertEqual(len(view["analysis_hash"]), 64)
        chat.assert_called_once()
        args = chat.call_args.kwargs
        payload = json.loads(args["user"])
        self.assertEqual(len(payload["templates"]), 9)
        self.assertEqual(len(payload["style_examples"]["examples"]), 9)
        self.assertNotIn("candidates", payload)
        self.assertFalse(args["retry_rate_limits"])
        for private in ("private-key", "raw-private-body", "raw-private-details", ".jpg", '"box"', "data:image"):
            self.assertNotIn(private, args["user"])
        self.assertEqual(args["response_format"]["type"], "json_schema")
        self.assertTrue(args["response_format"]["json_schema"]["strict"])
        self.assertNotIn("checks", view["items"][0])
        self.assertNotIn("fit_note", view["items"][0])

    def test_all_new_style_examples_fit_their_slots_and_use_unrelated_subjects(self):
        examples = STYLE_EXAMPLES["examples"]
        self.assertEqual({example["template_id"] for example in examples}, set(TEMPLATES))
        for example in examples:
            card = {**example, "id": "overview", "alt_text": example["why_it_works"]}
            prepared = prepare_meme_input({"summary": example["finding"]})
            validate_meme_view({"items": [card]}, prepared)
        text = json.dumps(STYLE_EXAMPLES).lower()
        for term in ("iran", "blockade", "midterms", "airstrikes", "gas prices"):
            self.assertNotIn(term, text)

    def test_final_response_requires_quality_checks_and_a_template_fit_explanation(self):
        for check in ("grounded", "mechanism_fits", "clear_without_report", "plain_language", "distinct"):
            response = final_response_for()
            response["items"][0]["checks"][check] = False
            with self.subTest(check=check), self.assertRaises(ValueError):
                validate_generated_response(response, prepare_meme_input(RESULTS))
        response = final_response_for(); response["items"][0]["fit_note"] = ""
        with self.assertRaises(ValueError):
            validate_generated_response(response, prepare_meme_input(RESULTS))

    def test_new_explanations_are_limited_to_twenty_words(self):
        response = response_for(); response["items"][0]["sentence"] = "word " * 21
        with self.assertRaises(ValueError):
            validate_meme_view(response, prepare_meme_input(RESULTS))

    def test_response_must_cover_exactly_the_existing_findings_and_valid_slots(self):
        prepared = prepare_meme_input(RESULTS)
        bad_responses = []
        missing = response_for(); missing["items"].pop(); bad_responses.append(missing)
        duplicate = response_for(); duplicate["items"][1] = duplicate["items"][0]; bad_responses.append(duplicate)
        unknown = response_for(); unknown["items"][0]["template_id"] = "../../other"; bad_responses.append(unknown)
        wrong = response_for(); wrong["items"][0]["captions"] = {"top": "Wrong slot"}; bad_responses.append(wrong)
        long = response_for(); long["items"][0]["captions"]["rejected"] = "word " * 20; bad_responses.append(long)
        missing_sentence = response_for(); missing_sentence["items"][0]["sentence"] = ""; bad_responses.append(missing_sentence)
        for response in bad_responses:
            with self.subTest(response=response), self.assertRaises(ValueError):
                validate_meme_view(response, prepared)
        reverse = response_for(); reverse["items"].reverse()
        cleaned = validate_meme_view(reverse, prepared)
        self.assertEqual(cleaned["items"][0]["id"], "overview")

    @patch("clearframe.memes.api_chat")
    def test_invalid_output_stops_after_one_call_without_correction(self, chat):
        rejected = final_response_for()
        rejected["items"][0]["checks"]["mechanism_fits"] = False
        for invalid in ('{"items": []}', 'not JSON', json.dumps(rejected)):
            with self.subTest(response=invalid):
                chat.reset_mock()
                chat.return_value = invalid
                with self.assertRaisesRegex(RuntimeError, "usable meme output"):
                    generate_meme_view(RESULTS, Mock())
                self.assertEqual(chat.call_count, 1)

    def test_rate_limits_do_not_trigger_an_extra_model_call(self):
        client = Mock()
        response = httpx.Response(429, request=httpx.Request("POST", "https://example.org"))
        client.chat.completions.create.side_effect = RateLimitError("Rate limited", response=response, body=None)
        with patch("clearframe.llm.time.sleep") as sleep:
            with self.assertRaises(RateLimitError):
                generate_meme_view(RESULTS, client)
        client.chat.completions.create.assert_called_once()
        sleep.assert_not_called()

    @patch("clearframe.memes.api_chat")
    def test_empty_or_invalid_analysis_makes_no_calls(self, chat):
        self.assertEqual(generate_meme_view({"summary": "", "categories": []}, Mock())["items"], [])
        for data in ([], {"categories": "bad"}, {"summary": []}, {"categories": [None]}):
            with self.assertRaises(ValueError):
                generate_meme_view(data, Mock())
        chat.assert_not_called()

    def test_an_unwritable_export_does_not_hide_completed_results(self):
        sink = queue.Queue()
        with patch("app.run_clearframe_pipeline", return_value={"synthesis": {"summary": "Finished", "categories": {}}}), patch("app._write_results_json", side_effect=OSError("read-only")):
            app.stream_pipeline("https://example.org", "test-key", sink)
        events = list(sink.queue)
        self.assertEqual([event["type"] for event in events][-2:], ["result", "done"])
        self.assertEqual(events[-2]["data"]["summary"], "Finished")


class MemeEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/memes"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()

    def post(self, body):
        request = Request(self.url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        try:
            response = urlopen(request)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response), response.headers

    @patch("app.AUTH_PASSWORD", "")
    @patch("app.OpenAI")
    @patch("app.generate_meme_view")
    def test_endpoint_uses_callers_key_without_writing_results(self, generate, client):
        view = validate_meme_view(response_for(), prepare_meme_input(RESULTS))
        generate.return_value = view
        with patch("app._write_results_json") as write:
            status, payload, headers = self.post({"api_key": "visitor-key", "results": RESULTS})
        self.assertEqual(status, 200)
        self.assertEqual(payload["meme_view"], view)
        self.assertEqual(headers["Cache-Control"], "no-store")
        client.assert_called_once_with(api_key="visitor-key", timeout=90, max_retries=0)
        self.assertEqual(generate.call_args.args[0], RESULTS)
        write.assert_not_called()

    @patch("app.AUTH_PASSWORD", "")
    @patch("app.OpenAI")
    def test_invalid_requests_are_rejected_before_a_model_call(self, client):
        for body in ([], {}, {"api_key": "key", "results": []}, {"api_key": "key", "results": {"summary": ""}}):
            status, payload, _ = self.post(body)
            self.assertEqual(status, 400)
            self.assertIn("error", payload)
        client.assert_not_called()

    @patch("app.AUTH_PASSWORD", "")
    @patch("app.OpenAI")
    @patch("app.generate_meme_view", side_effect=RuntimeError("secret visitor-key"))
    def test_upstream_failure_does_not_echo_credentials(self, generate, client):
        status, payload, _ = self.post({"api_key": "visitor-key", "results": RESULTS})
        self.assertEqual(status, 502)
        self.assertNotIn("visitor-key", json.dumps(payload))

    @patch("app.AUTH_PASSWORD", "password")
    def test_endpoint_obeys_the_existing_password_gate(self):
        request = Request(self.url, data=b"{}", headers={"Content-Type": "application/json"})
        with self.assertRaises(HTTPError) as raised:
            urlopen(request)
        self.assertEqual(raised.exception.code, 401)
        raised.exception.close()


if __name__ == "__main__":
    unittest.main()
