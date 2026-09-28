# 086 — 저장된 양식 선택의 실제 Planning 연결 결과

## 결과와 범위

고정 084 응답 6개를 실제 compiled Planning에 재생한 component gate는 **6 PASS / 0 FAIL**이다.
각 응답의 Product final draft와 terminal ANSWER_DRAFT 본문이 084의 검증된 draft와 정확히 같다.
신규 LLM·Provider·WRITE 호출은 모두 0이다. 이는 저장된 응답의 연결 검증이며 새 모델 성공률,
전체 업무 성공, Canonical 92 성적 또는 Production activation을 의미하지 않는다.

| 저장 응답 | 양식 | 연결 결과 | 보존한 경계 |
| --- | --- | --- | --- |
| CORE005 lookup T1/T2 | FACT_REFERENCES | PASS ×2 | 상태·기한 draft, 현재 component Run의 Answer artifact, terminal 본문 |
| 합성 completed T1/T2 | FACT_REFERENCES | PASS ×2 | 상태·메모·identity 표시 draft와 승인 Evidence refs |
| 합성 정리 T1/T2 | PROSE | PASS ×2 | 원문 비인용 정리 draft와 승인 Evidence refs |

각 replay의 semantic adapter 진입은 정확히 1회이며 추론 호출이 아니다. 실제 outline/compose
runtime projection의 snapshot resolution은 각각 2회, 모두 해당 새 component Run에서 RESOLVED다.
`preserves_084_validated_draft`와 `inputs_unchanged`는 6/6 true다. terminal composer는 0회이며
terminal kind는 모두 `COMPLETE_ANSWER_ONLY`다. Artifact ID는 각 component Run에 속하는
`086-<case_id>:answer`로 생성됐다. 의미 판정 필드는 모두 `NOT_EVALUATED`로 보존했다.

## 실행 근거

- 실행 HEAD: `948904ea7c2527fcba8a5f5e205724a8c30aebbd`.
- 결과: `evaluation/results/086-answer-choice-handoff-t1/raw.json`.
- 결과 byte SHA256: `43a5cd05b072fb447826a926c22b1aaf6b7aaa91789ecd049cbaf9f366d8ffac`.
- 원 084 raw SHA256: `3ce662090733ad1d7c8811a566f8f4541514198463212b69615540beca6a8a1b`.
- read-only 원 DB SHA256: `5838f3d98b1caedc78a44d195d4cca7fcde693fc483aacf5432955c9a8987f70`.
- 고정 checkpoint blob SHA256: `f86e3ad415149615f8f0a79ef1efd172df1dc8db2ee7abf6dece2d08687a0d44`.
- `completed=true`, `binding_unchanged=true`, `component_verdict=PASS`.

082의 checkpoint loader, RunScopedEvidenceStore, 실제 Planning graph, compose validator,
Answer artifact owner 및 terminal-intent builder를 재사용했다. 바꾼 것은 평가 모듈이 참조하는
materializer의 scoped 주입뿐이다. Product 함수를 patch하거나 원 checkpoint를 resume하지 않았다.
CORE005는 실제 고정 checkpoint를, 합성 두 입력은 명시적인 synthetic ANSWER route를 사용했다.
정리 입력을 과거 실제 upstream이 생성한 것으로 표시하지 않는다.

## 판단과 남은 검증

084의 FACT/PROSE 결과를 기존 AnswerDraftCandidate로 materialize하여 실제 소비 경계에
전달할 수 있다는 **연결 후보 근거는 확인**했다. 084의 독립 의미 검수 결과를 이번 component
점수에 새 모델 시행으로 합산하지 않는다. Product 반영과 Prompt 활성화는 하지 않았다.

실제 Main/Supervisor merge, DB terminal commit, UI delivery, 새로운 RU/Tool Route/조회,
일반 ANSWER eligibility, 다중 Resource, snapshot 없는 일반 PROSE 및 실패 시 제품 경로는
별도 검증 범위다. 현재 helper의 지원 catalog가 없으면 기존 Product wire를 그대로 선택하는
pre-dispatch 계약과 실제 router 연결은 이 gate가 증명하지 않는다.

086의 same-Run snapshot 요구는 이 여섯 저장 응답의 provenance 확인이다. 이를 모든 PROSE에
대한 새로운 snapshot 필수 정책으로 확대하면 안 된다. Product 채택 시 snapshot은 private
caller에서 소비하고, Prompt input에는 허용되지 않은 sidecar를 추가하지 않아야 한다.
상세 raw는 기존 evaluation/results 로컬 보관 규약을 따르며 위 요약·hash만 버전관리한다.
