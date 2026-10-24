import os
import unittest
from unittest.mock import patch
import jev_gemini_router as router


def jev_answer(route="simple_task", confidence=0.99):
    return {"model": "jev-1.13.0", "answers": {"route": {
        "type": "choice", "choice": route, "confidence": confidence,
        "probabilities": {route: confidence},
    }}, "usage": {"input_tokens": 80, "output_tokens": 20}}


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"TYPESAFE_API_KEY": "jev-test-key",
                                        "GEMINI_API_KEY": "gemini-test-key"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.calls = []

    def transport(self, url, payload, headers, timeout):
        self.calls.append((url, payload, headers, timeout))
        if url == router.JEV_ENDPOINT:
            return jev_answer(self.jev_route, self.confidence)
        return {"candidates": [{"content": {"parts": [{"text": "Generated answer"}]}}],
                "usageMetadata": {"promptTokenCount": 7}}

    jev_route = "simple_task"
    confidence = 0.99

    def test_simple_routes_to_flash_lite(self):
        result = router.handle("Summarize this short text", self.transport)
        self.assertEqual(result["model"], router.CHEAP_MODEL)
        self.assertIn(router.CHEAP_MODEL, self.calls[1][0])
        self.assertEqual(result["usage"]["jev"]["input_tokens"], 80)
        self.assertEqual(result["usage"]["gemini"]["promptTokenCount"], 7)

    def test_complex_routes_to_pro(self):
        self.jev_route = "complex_task"
        self.assertEqual(router.handle("Analyze race conditions", self.transport)["model"],
                         router.COMPLEX_MODEL)

    def test_low_confidence_simple_escalates(self):
        self.confidence = 0.6
        self.assertEqual(router.handle("Analyze this", self.transport)["model"],
                         router.COMPLEX_MODEL)

    def test_review_sends_no_gemini_request(self):
        self.jev_route = "needs_review"
        result = router.handle("Need review", self.transport)
        self.assertEqual(result["route"], "requires_review")
        self.assertEqual(len(self.calls), 1)

    def test_other_sends_no_gemini_request(self):
        self.jev_route = "other"
        self.assertEqual(router.handle("Unknown", self.transport)["model"], None)
        self.assertEqual(len(self.calls), 1)

    def test_deterministic_faq_no_api_calls(self):
        self.assertEqual(router.handle("What is 2 + 2?", self.transport)["route"],
                         "deterministic")
        self.assertEqual(self.calls, [])

    def test_malformed_jev_fails_without_gemini_request(self):
        def bad(url, payload, headers, timeout):
            self.calls.append(url)
            return {"answers": {"route": {"type": "choice", "choice": "unknown",
                                           "confidence": 0.99}}}
        with self.assertRaises(router.RoutingError):
            router.handle("Prompt", bad)
        self.assertEqual(self.calls, [router.JEV_ENDPOINT])

    def test_invalid_confidence_fails(self):
        self.confidence = True
        with self.assertRaises(router.RoutingError):
            router.handle("Prompt", self.transport)
        self.assertEqual(len(self.calls), 1)

    def test_input_validation_no_api_calls(self):
        for prompt in ("", "  ", "a" * (router.MAX_PROMPT_CHARS + 1)):
            with self.subTest(prompt_len=len(prompt)):
                with self.assertRaises(router.RoutingError):
                    router.handle(prompt, self.transport)
        self.assertEqual(self.calls, [])

    def test_upstream_failure_no_model_call(self):
        def fail(url, payload, headers, timeout):
            self.calls.append(url)
            raise router.RoutingError("Upstream request failed or timed out")
        with self.assertRaises(router.RoutingError):
            router.handle("Prompt", fail)
        self.assertEqual(self.calls, [router.JEV_ENDPOINT])

    def test_jev_request_matches_documented_schema(self):
        router.handle("Prompt", self.transport)
        url, payload, headers, timeout = self.calls[0]
        self.assertEqual(url, "https://api.typesafe.ai/v1/systemone")
        self.assertEqual(payload["model"], router.JEV_MODEL)
        self.assertEqual(payload["questions"]["route"]["type"], "choice")
        self.assertTrue(headers["Authorization"].startswith("Bearer "))

if __name__ == "__main__":
    unittest.main()
