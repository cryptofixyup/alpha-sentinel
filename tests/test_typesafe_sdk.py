"""Real SDK serialization/decoding through an in-memory transport; no network."""
import json
import unittest

import httpx2
from typesafe_sdk import AsyncTypeSafeClient

from typesafe_labeler import CRITERIA, SecurityLabel, classify_text


class SDKCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_sdk_request_and_response(self):
        requests = []
        def handler(request):
            requests.append(json.loads(request.content))
            return httpx2.Response(200, json={
                "model": "offline-fixture",
                "answers": {"security_label": {
                    "type": "choice", "choice": "unknown", "confidence": 0.9,
                    "probabilities": {key: float(key == "unknown") for key in CRITERIA},
                }},
                "usage": {"input_tokens": 0, "output_tokens": 0},
            })
        async with AsyncTypeSafeClient(api_key="offline-test-key", model="jev-latest",
                                       transport=httpx2.MockTransport(handler)) as client:
            result = await classify_text(" ambiguous evidence ", client)
        self.assertEqual(result.label, SecurityLabel.UNKNOWN)
        self.assertEqual(requests[0]["state"], {"text": "ambiguous evidence"})
        question = requests[0]["questions"]["security_label"]
        self.assertEqual(question["type"], "choice")
        self.assertEqual(question["criteria"], dict(CRITERIA))

    async def test_real_sdk_incomplete_distribution_is_rejected(self):
        def handler(request):
            return httpx2.Response(200, json={
                "model": "offline-fixture",
                "answers": {"security_label": {"type": "choice", "choice": "unknown",
                    "confidence": 0.9, "probabilities": {"unknown": 1.0}}},
                "usage": {"input_tokens": 0, "output_tokens": 0},
            })
        async with AsyncTypeSafeClient(api_key="offline-test-key",
                                       transport=httpx2.MockTransport(handler)) as client:
            with self.assertRaises(ValueError):
                await classify_text("evidence", client)
