import json
from pathlib import Path
import unittest

from typesafe_labeler import CRITERIA


class EvaluationFixtureTests(unittest.TestCase):
    def test_fixture_ids_labels_and_category_coverage(self):
        path = Path(__file__).resolve().parents[1] / "fixtures/typesafe/evaluation.json"
        fixture = json.loads(path.read_text())
        cases = fixture["cases"]
        self.assertEqual(fixture["schema_version"], 1)
        self.assertEqual(len({case["id"] for case in cases}), len(cases))
        self.assertEqual({case["expected"] for case in cases}, set(CRITERIA))
        for case in cases:
            self.assertTrue(case["text"].strip())
            self.assertTrue(case["rationale"].strip())
