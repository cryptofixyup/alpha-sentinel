import os
import unittest
from unittest.mock import patch
import jev_gemini_router as router


def jev_answer(route="simple_task", confidence=0.99):
    return {"model": "jev-1.13.0", "answers": {"route": {
        "type": "choice", "choice": route, "confidence": confidence,
        "probabilities": {
            key: (confidence if key == route else (1 - confidence) / 3)
            for key in ("simple_task", "complex_task", "needs_review", "other")
        },
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


    def test_incomplete_probabilities_fail_closed(self):
        def incomplete(url, payload, headers, timeout):
            self.calls.append(url)
            response = jev_answer()
            response["answers"]["route"]["probabilities"] = {"simple_task": 0.99}
            return response
        with self.assertRaises(router.RoutingError):
            router.handle("Prompt", incomplete)
        self.assertEqual(self.calls, [router.JEV_ENDPOINT])

    def test_selected_choice_must_match_probability_maximum(self):
        def inconsistent(url, payload, headers, timeout):
            self.calls.append(url)
            response = jev_answer()
            response["answers"]["route"]["choice"] = "complex_task"
            return response
        with self.assertRaises(router.RoutingError):
            router.handle("Prompt", inconsistent)
        self.assertEqual(self.calls, [router.JEV_ENDPOINT])


    def assert_answer_rejected(self, answer):
        calls = []

        def transport(url, payload, headers, timeout):
            calls.append(url)
            if url != router.JEV_ENDPOINT:
                self.fail("Rejected classifier response reached Gemini")
            return {"answers": {"route": answer}}

        with self.assertRaises(router.RoutingError):
            router.handle("Prompt", transport)
        self.assertEqual(calls, [router.JEV_ENDPOINT])

    def test_probability_shapes_fail_closed(self):
        valid = jev_answer()["answers"]["route"]["probabilities"]
        cases = {
            "missing": None,
            "list": list(valid.values()),
            "empty": {},
            "extra_key": {**valid, "unexpected": 0.0},
            "wrong_key": {**{k: v for k, v in valid.items() if k != "other"},
                          "unexpected": valid["other"]},
            "sum_too_low": dict.fromkeys(valid, 0.1),
            "sum_too_high": dict.fromkeys(valid, 0.4),
            "tie": {"simple_task": 0.4, "complex_task": 0.4,
                    "needs_review": 0.1, "other": 0.1},
        }
        for name, probabilities in cases.items():
            with self.subTest(case=name):
                answer = jev_answer()["answers"]["route"]
                answer["probabilities"] = probabilities
                self.assert_answer_rejected(answer)

    def test_invalid_probability_values_fail_closed(self):
        cases = (True, False, None, "0.99", [], {},
                 float("nan"), float("inf"), float("-inf"), -0.01, 1.01)
        for key in ("simple_task", "complex_task", "needs_review", "other"):
            for value in cases:
                with self.subTest(key=key, value=value):
                    answer = jev_answer()["answers"]["route"]
                    answer["probabilities"][key] = value
                    self.assert_answer_rejected(answer)

    def test_invalid_confidences_fail_closed(self):
        cases = (True, False, None, "0.99", [], {},
                 float("nan"), float("inf"), float("-inf"), -0.01, 1.01)
        for value in cases:
            with self.subTest(confidence=value):
                answer = jev_answer()["answers"]["route"]
                answer["confidence"] = value
                self.assert_answer_rejected(answer)

    def test_confidence_is_independent_of_selected_probability(self):
        for confidence, expected_model in (
                (0.0, router.COMPLEX_MODEL),
                (0.6, router.COMPLEX_MODEL),
                (0.9, router.CHEAP_MODEL),
                (1.0, router.CHEAP_MODEL)):
            with self.subTest(confidence=confidence):
                self.calls = []

                def transport(url, payload, headers, timeout):
                    if url == router.JEV_ENDPOINT:
                        self.calls.append((url, payload, headers, timeout))
                        response = jev_answer()
                        answer = response["answers"]["route"]
                        answer["confidence"] = confidence
                        answer["probabilities"] = {
                            "simple_task": 0.7, "complex_task": 0.2,
                            "needs_review": 0.1, "other": 0.0}
                        return response
                    return self.transport(url, payload, headers, timeout)

                result = router.handle("Prompt", transport)
                self.assertEqual(result["classifier_confidence"], confidence)
                self.assertEqual(result["model"], expected_model)
                self.assertEqual(len(self.calls), 2)

    def test_normalization_tolerance(self):
        for delta, accepted in ((0.0000005, True), (-0.0000005, True),
                                (0.000002, False), (-0.000002, False)):
            with self.subTest(delta=delta):
                answer = jev_answer()["answers"]["route"]
                answer["probabilities"] = {
                    "simple_task": 0.7, "complex_task": 0.2,
                    "needs_review": 0.1 + delta, "other": 0.0}
                if accepted:
                    route, confidence = router.validate_choice(answer)
                    self.assertEqual((route, confidence), ("simple_task", 0.99))
                else:
                    self.assert_answer_rejected(answer)

if __name__ == "__main__":
    unittest.main()
