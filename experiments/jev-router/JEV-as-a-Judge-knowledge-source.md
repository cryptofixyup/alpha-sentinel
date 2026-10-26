# JEV-as-a-Judge: Knowledge Source for Our Judge

**Source:** Yubo Li, Yidi Miao, Ramayya Krishnan, Rema Padman, *JEV-as-a-Judge: Accept When Confident, Escalate When Unsure*, arXiv:2609.26550v1, 22 September 2026. [Paper page](https://academy.dair.ai/papers/jev-as-a-judge-accept-when-confident-escalate-when-unsure-2609.26550) · [arXiv PDF](https://arxiv.org/pdf/2609.26550)

**Status:** External research input. This note summarizes reported findings and derives candidate engineering requirements. It does not certify our judge, set production thresholds, or change any authorization policy.

## Why this paper matters

The paper tests whether a low-cost, decision-only judge can handle routine evaluations and identify uncertain cases for escalation to a stronger judge. It treats confidence as a routing signal whose usefulness must be measured, rather than as proof that a verdict is correct.

## Reported findings

- On the authors’ sampled RewardBench preference task, JEV scored 92.2% versus GPT-6’s 93.5%; on evidence-grounded HaluEval, 87.5% versus 86.7%; and on their existing final-answer adjudication set, 94.0% versus 96.7%.
- JEV scored 78.6% on JudgeBench, compared with 93.1% for GPT-5.6 and GPT-6. The largest gaps were on reasoning and coding judgments.
- On RM-Bench, JEV was less reliable when the incorrect answer was more elaborately written: 74.8% on those hard pairs versus GPT-6’s 94.6%.
- On a 510-pair held-out preference set, a frozen policy accepting JEV verdicts above 0.9 confidence and escalating the rest to GPT-6 Astra reached 92.5%, versus 93.1% for GPT-6 alone, at about 57% of GPT-6’s measured fee.
- On the paper’s reference-free prose sample, all tested judges were near chance while remaining highly confident. Confidence therefore failed as a universal error detector.
- The paper reports that a threshold that worked with one fallback did not transfer reliably to every alternative fallback. Thresholds require local selection and re-evaluation.

These are measurements on the authors’ datasets, prompts, model versions, and evaluation setup. They are not expected accuracy or cost guarantees for our workload.

## Operational lessons for our judge

1. **Use confidence to route scrutiny, not grant authority.** A judge may return a recommendation and calibrated uncertainty metadata. It must never create authorization or skip deterministic controls.
2. **Define task classes and evidence availability.** Separate preference ranking, evidence-grounded factuality, derivation/math/coding verification, style-sensitive comparisons, reference-free prose, and extraction tasks. Do not assume one confidence policy works across them.
3. **Escalate on uncertainty and known hard-case signals.** Low confidence, missing or conflicting evidence, reasoning/derivation requirements, suspected persuasive-but-wrong content, and unsupported reference-free claims should lead to abstention or stronger review. Local deterministic checks should be used where possible.
4. **Calibrate locally.** Choose thresholds on a versioned selection set representative of the task and fallback judge. Freeze the policy before held-out evaluation. Recheck after changing model, rubric, prompt, data distribution, or fallback.
5. **Measure selective risk, not just overall accuracy.** Track coverage (accepted share), accuracy/error among accepted cases, escalation rate, fallback outcomes, cost, latency, and invalid-output rate. Report results by task class and high-impact failure type.
6. **Make outputs fail closed.** Validate schema, allowed labels, finite normalized probabilities, verdict/probability consistency, and required evidence references. Invalid, missing, timed-out, or malformed results are not approvals; treat them as errors/abstentions and route according to policy. Do not silently repair a judge output into an accepted verdict.
7. **Test for judge bias and instability.** For pairwise ranking, test both candidate orders. Add rubric paraphrases, repeated calls, adversarially persuasive wrong answers, evidence removal/conflict, and style perturbations. Keep source items grouped when splitting train/selection/test to avoid leakage.
8. **Retain traceable records.** Record judge/model and rubric versions, input/evidence identifiers or hashes, probabilities, threshold/policy version, validation result, escalation target, final disposition, and timing/cost metadata. Preserve privacy constraints on content.

## Candidate decision contract

```text
JudgeResult = {
  verdict: AllowedLabel | ABSTAIN,
  probabilities: Map<AllowedLabel, finite probability>,
  evidence_refs: [EvidenceId],
  task_class: TaskClass,
  model_version: Version,
  rubric_version: Version,
  policy_version: Version
}
```

The caller validates this contract. A threshold may produce `ACCEPT_FOR_ROUTINE_REVIEW` only for a locally validated task class and policy version. Otherwise it produces `ESCALATE` or `ABSTAIN`. These states describe evaluation workflow only; they are not transaction or system authorization states.

## Proposed evaluation gates (not yet demonstrated in our system)

- Freeze a representative, labeled local dataset and split by source item into threshold-selection and held-out evaluation sets.
- Evaluate baseline judge and fallback on identical examples; include human adjudication for disagreements on consequential labels where feasible.
- Test confidence calibration and selective risk by task class, including Brier score or another proper scoring rule, error-detection performance, coverage-risk curves, and confidence-conditioned error rates.
- Test ordering/reversal, prompt/rubric paraphrase, repeatability, persuasive incorrect answers, missing/conflicting evidence, and reference-free inputs.
- Count invalid outputs and operational failures as non-accepted outcomes; expose denominators and retain retry/failure data.
- Compare the frozen cascade with the strong judge alone on held-out quality, escalation fraction, observed cost, and latency. Set acceptance thresholds from product risk, not from the paper’s 0.9 example.
- Re-run these gates whenever model, rubric, prompt, task mix, evidence source, or fallback changes.

## Architecture mapping

In our authority-separated design, the judge is an **evaluation and routing component**. It may propose a verdict, confidence, and escalation recommendation. A separate deterministic policy evaluates the required evidence, risk limits, state, and approvals. Cryptographic binding and isolated signing remain downstream controls; judge confidence cannot satisfy them. Every escalation or denial should be explicit and auditable.

## Evidence classification

- **Demonstrated by this paper:** Reported benchmark results and the tested preference-pair cascade under the authors’ frozen setup.
- **Inference for our architecture:** A locally validated cascade may reduce routine judging cost while preserving a defined quality target.
- **Not demonstrated for our judge:** Local accuracy/calibration, appropriate thresholds, resistance to our threat model, calibration transfer, safe behavior on our inputs, and production reliability. These require repository implementation and reproducible tests.

## Citation

Li, Y., Miao, Y., Krishnan, R., & Padman, R. (2026). *JEV-as-a-Judge: Accept When Confident, Escalate When Unsure*. arXiv:2609.26550v1. https://arxiv.org/abs/2609.26550
