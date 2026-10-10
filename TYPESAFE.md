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

The tests use a mocked SDK module and client. They verify application boundary
behavior, not actual SDK compatibility or model accuracy. A real SDK installation
and representative labeled evaluation are required before production enablement.
No API calls are needed to run these tests.

API reference: https://docs.typesafe.ai/sdk/python
