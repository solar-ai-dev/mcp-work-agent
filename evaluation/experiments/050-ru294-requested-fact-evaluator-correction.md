# #294 Requested-Fact Evaluator Correction

Owning issue: #294

## Audit result

- Overall: `MIXED`
- Original RU v2 Dataset: `DATASET_OK`
- Historical derived evaluation: `DERIVED_GOLD_DEFECT`, `GRADER_DEFECT`, `VALIDATOR_DEFECT`
- Original Dataset confirmed defects: 0
- Dataset: 24 cases, 8 semantic families × 3, EASY/COMPOSITE/HARD 각 8
- Dataset SHA-256: `db1e86c80f67db113baa28626bbd14f014ed3d18c26c7452077547ed6dd6d59d`

Historical v1의 문제는 identity/requested-result 분리 근거 부족,
`allowed_semantic_variations` 처리 부재, high-level meaning의 closed fact-kind 강제 변환,
`RU-A-003` strict force-fail, constraint-overlap provenance false reject였다. v1 reference,
scorer, tests는 `HISTORICAL_ONLY / INVALID_FOR_FINAL_COMPARISON`로 유지한다.

## Corrected v2 contract

- Evaluator commit: `40fb5c23fc5bb5e9517b3d13a48acce99c5b6220`
- Reference: `evaluation/ru294_direct_fact_reference_13_v2.json`
- Reference SHA-256: `80661f51f13a7a25116f0f8d81244a7ae8495f0916ee6736dd4bd915f7e054a3`
- Scorer: `ru294-requested-fact-evaluator-v2`
- Scorer SHA-256: `0977fad35ca8520eda64ebe30df7e7338170e1b784157e0c04d81ed8a65031cc`
- Provenance validator: `ru294-exact-span-with-overlap-diagnostic-v2`

Applicability:

- `SCORABLE` 8: closed owner fact kind로 direct result/current state를 정확히 표현 가능
- `NOT_APPLICABLE` 3: `RU-D-001`, `RU-E-003`, `RU-G-003`
- `UNSCORABLE` 2: `RU-A-003`, `RU-B-002`

Constraint overlap은 diagnostic으로만 기록하며 exact source span을 무효화하지 않는다.
Identity는 source-binding diagnostic으로 user-result scoring과 분리한다. Fact-kind variation은
Product resource owner 경계를 유지하며 다른 owner의 kind를 alias로 허용하지 않는다.
Reference는 target 9/control 4, inclusion reason, intended failure signature를 기록한다.

## Raw compatibility and Phase C rescore

- Minimal saved provider responses: 25, complete raw pairs 12, timeout envelope 1
- Concise saved provider responses: 26, complete raw pairs 13
- Raw first-response를 직접 읽어 v2로 재채점
- Existing observations는 token/latency와 runtime metadata에만 사용
- Qwen/provider calls: 0
- Timeout retry: 0
- Artifact: `evaluation/results/ru294-corrected-v2-rescore-20260920/rescore.json`
- Artifact SHA-256: `e164f38eb03a099387f621e1f37abbca32db0519f91c722be6e671553cb9f9bb`

결과 요약:

- Minimal: A 2/8 → B 0/8, FAIL→PASS 0, PASS→FAIL 2 — [048](048-ru294-minimal-fewshot.md)
- Concise: A 2/8 → B 1/8, FAIL→PASS 0, PASS→FAIL 1 — [049](049-ru294-concise-zeroshot.md)

## Decision

- Minimal few-shot: `REJECT`
- Concise zero-shot: `REJECT`
- Candidate F: `NOT RUN / HOLD`

## Runtime exclusion evidence

#303 저장 evidence는 두 structured endpoint 모두 schema-valid 5/5, semantic-valid 0/5,
정상 termination이었다. #294 실패를 endpoint 차이로 설명하기 어렵다는 참고 근거로만
사용했으며 #303 파일, 별도 record, Issue comment는 이번 범위에 포함하지 않았다.

## Revisit condition

Candidate F 또는 다른 producer 구조를 실행하려면 corrected v2 contract와 target/control을
고정하고 별도 실행 승인을 받아야 한다.
