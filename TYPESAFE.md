# Optional TypeSafe advisory labeling

Install `requirements-typesafe.txt` and set `TYPESAFE_API_KEY` server-side.
The existing OpenAI provider remains the default.

```python
from auto_labeler import label_text
from typesafe_labeler import classify_text

label = await label_text(text, provider="typesafe")  # bounded string
judgment = await classify_text(text)  # enum, probabilities, confidence
```

The category rubric lives in `typesafe_labeler.py`. Unknown means insufficient
or ambiguous semantic evidence. Transport errors and malformed responses raise
exceptions; callers must handle them separately. No label authorizes an action,
and no-security-signal is not a safety certification. No confidence cutoff is
claimed to be calibrated. Existing lifecycle and policy modules are untouched.

Run the offline boundary tests:

```bash
python -m unittest discover -s tests -p test_typesafe_labeler.py -v
```

Install the pinned optional dependency, then run all TypeSafe checks:

```bash
python -m pip install -r requirements-typesafe.txt
python -m unittest discover -s tests -p 'test_typesafe*.py' -v
```

Boundary tests use mocked clients. SDK compatibility tests use the installed
0.7.4 SDK with an in-memory HTTP transport to check real request serialization
and response decoding. CI installs the pinned dependency and runs both.
No network calls or API credentials are needed for these tests.

`fixtures/typesafe/evaluation.json` contains 18 synthetic cases with provisional
expected labels and rationales: three per category, including ambiguous and
instruction-override cases. These are an initial review set, not model results
or a calibrated benchmark. Review labels before a bounded live evaluation;
record per-category errors, confusion, unknown rates, actual model version,
latency, token usage, and service failures. No model accuracy is claimed here.
The SDK pin does not pin the remote model alias.

API reference: https://docs.typesafe.ai/sdk/python
