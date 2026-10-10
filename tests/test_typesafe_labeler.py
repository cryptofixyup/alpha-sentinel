import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from typesafe_labeler import CRITERIA, SecurityLabel, classify_text


def response(choice="unknown", **overrides):
    fields = dict(choice=choice, confidence=0.9,
                  probabilities={key: float(key == choice) for key in CRITERIA})
    fields.update(overrides)
    return SimpleNamespace(choices={"security_label": SimpleNamespace(**fields)})


class LabelerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sdk = SimpleNamespace(AsyncTypeSafeClient=object,
                                   Choice=lambda **kwargs: kwargs)
        self.patch = patch.dict(sys.modules, {"typesafe_sdk": self.sdk})
        self.patch.start()
        self.addCleanup(self.patch.stop)

    async def test_unknown_is_explicit_and_client_is_caller_owned(self):
        client = SimpleNamespace(system_one=AsyncMock(return_value=response()), close=AsyncMock())
        result = await classify_text(" ambiguous evidence ", client)
        self.assertEqual(result.label, SecurityLabel.UNKNOWN)
        self.assertEqual(client.system_one.call_args.kwargs["state"], {"text": "ambiguous evidence"})
        client.close.assert_not_called()
        with self.assertRaises(TypeError):
            result.probabilities["unknown"] = 0

    async def test_rejects_malformed_results(self):
        cases = [response(choice="invented"), response(probabilities={"unknown": 1}),
                 response(confidence=float("nan")), response(confidence=True),
                 response(probabilities={key: 0.1 for key in CRITERIA}),
                 response(choice="unknown", probabilities={key: float(key == "other_security") for key in CRITERIA})]
        for result in cases:
            with self.subTest(result=result), self.assertRaises(ValueError):
                await classify_text("evidence", SimpleNamespace(system_one=AsyncMock(return_value=result)))

    async def test_service_failure_is_not_unknown(self):
        client = SimpleNamespace(system_one=AsyncMock(side_effect=TimeoutError("service failure")))
        with self.assertRaises(TimeoutError):
            await classify_text("evidence", client)

    async def test_rejects_empty_input_before_request(self):
        client = SimpleNamespace(system_one=AsyncMock())
        with self.assertRaises(ValueError):
            await classify_text(" ", client)
        client.system_one.assert_not_called()

    async def test_owned_client_exits_after_failure(self):
        active = SimpleNamespace(system_one=AsyncMock(side_effect=TimeoutError()))
        class Context:
            async def __aenter__(self):
                return active
            async def __aexit__(self, *args):
                closed.append(args[0])
        closed = []
        self.sdk.AsyncTypeSafeClient = Context
        with self.assertRaises(TimeoutError):
            await classify_text("evidence")
        self.assertEqual(closed, [TimeoutError])
