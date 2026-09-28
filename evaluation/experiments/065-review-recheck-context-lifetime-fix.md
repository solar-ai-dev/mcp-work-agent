# 065 — Review 재검사 문맥의 revision 수명 복구

기준 `3e126211`. Review v1~v3 의미 후보의 REJECT와 별개로 코드·Canonical·직접 테스트로
확정한 소비 경계 결함이다. 모델의 요청 의미를 코드로 대신 판단하지 않는다.

## 최초 손실과 수정

| 경계 | 이전 결함 | 수정 |
| --- | --- | --- |
| Supervisor upstream invalidation → Review entry | Request/Route/Retrieval/WorkAnalysis가 바뀌어 Plan·Review를 무효화해도 prompt_context의 과거 finding/dimension이 남아 새 계획을 RECHECK 일부 항목만 검사 | 해당 revision 변경 때 Review 전용3키만 폐기, 새 계획은 INITIAL |
| Planning-only revision | REVISE 아닌 이전 결과의 context도 prior Review=None이면 재검사 근거로 사용 | 바로 직전 Plan에 based_on한 REVISE만 예외적으로 context 재사용 |
| persisted ModifyAction → Review entry | 인자 수정 시 plan_review=None 직접 반환, Supervisor invalidation을 거치지 않아 오래된 selector 잔존 | 기존 full current-plan Review 계약대로 같은3키 제거, persisted Evidence·사용자 변경값은 유지 |
| Review aggregate → Supervisor context merge | 새 결과의 proposal capture가 불가능할 때 pop한 key가 merge에서 과거 값으로 복원 | 명시적 None으로 새 결과의 부재를 전달 |
| 정상 Planning revision → Review projection | 이전 Review가 이미 invalidated(None)이어서 보존된 previous proposal을 실제 recheck 입력으로 전달하지 않음 | 허용된 RECHECK의 saved proposal도 기존 route-local transition projector에 전달 |

Review 문맥3키는 `review_prior_findings`, `review_affected_dimensions`,
`review_previous_proposal`이다. 다른 Prompt context와 현재 same-Plan CONFIRM 응답은
보존한다. 같은 stage에서 새 Plan에 결속된 새 Review도 보존한다. 과거 Review status를
새 PASS/승인 권한으로 승격하지 않으며 Domain 승인·실행·검증 기록은 변경하지 않는다.
Modify 준비 후 WAITING_APPROVAL caller의 lifecycle→Supervisor merge가 한 번 더 있으므로
삭제한 key를 단순 생략하지 않고 명시적 None으로 남겨 재유입을 막았다. 이 caller도 실제
`project_lifecycle_control → project_supervisor_state` 직접 테스트로 검증했다.
이전 proposal은 두 Plan의 non-empty `based_on`이 동일할 때만 추가 입력에 전달한다.
ref가 없거나 upstream이 다른 legacy proposal은 소비하지 않는다.

owner는 기존 Main revision invalidation/Modify 준비와 Review producer·projection이다.
Canonical06 §2.4에 기존 제한적 RECHECK 예외의 수명을 명확히 했다. 새 Node/Edge/State/
Schema/Prompt/LLM 호출 종류/재시도 한도 추가0. 출력 finding의 의미 판단·severity aggregation은
그대로다. 잘못 생략됐던 INITIAL inspector 실행과 기존 proposal 입력을 복구하므로 이를
호출/토큰 감소로 주장하지 않는다. 실제 모델 총비용 차이는 미측정이다.

## 직접 검증

- 수정 전 신규 최초10개 **8 FAIL/2 PASS**: upstream5, non-REVISE3에서 stale context 재현.
- 첫 invalidation 수정 후 인접42 PASS/0.84초.
- 확장 직접·인접 **51 PASS/1.02초**. 신규15개 + Modify 기존 테스트의 old context 유/무.
- application agents / run use-cases / LangGraph adapters / Review 후보 직접 테스트
  최종 **2,188 PASS/16.84초**, 단일 pytest. 최초 확장2,187 PASS/15.30초와 중복이므로
  합산하지 않는다. 전체 repository pytest/실제 모델 평가가 아니다.
- Product4파일 + 직접 테스트2파일 mypy PASS, 관련 Ruff PASS.

테스트는 실제 invalidate/Review entry 및 production-dependency projection/aggregate →
actual Supervisor merge를 사용한다. 정상 Planning-only REVISE, same-Plan confirmation,
다른 Plan을 가리키는 stale Review, 새 Plan의 fresh Review, dimension-only REVISE,
변경 argument/historical issue 전달, persisted Evidence 보존을 대조했다. fake runtime의
semantic calls는0이며 모의 정답을 실제 모델 의미 성공으로 보고하지 않는다.

## 한계·다음 경계

기존 028/033의 proposal-transition 모델 근거는 역사 기록으로 유지하며 현재 SHA 점수로
승계하지 않는다. 이번 수정에서 새 모델/Graph 전체/Provider/승인 실행0, rerun-to-pass0.
이미 과거 checkpoint에 unbound stale context가 저장돼 다음 invalidation 없이 REVIEW에
직접 진입하는 상태까지 자동 복구했다고 주장하지 않는다. 기존 checkpoint를 수정하거나
resume-version gate를 우회하지 않았다. 다만 이전 인자를 이번에 추가로 노출하는 경계는
위 based_on 대조로 제한했다. 오래된 제한 검사 selector 자체의 migration과는 구분한다.

Request Output 의미 오판과 Review의 typed owner 오귀속/누락은 아직 남아 있다. 이 수정은
그 문제를 해결한 것이 아니라 새 의미·새 근거를 과거 검사 범위로 축소하는 전달 결함과
정상 수정 비교 누락을 막은 것이다. 추가 모델 후보 전에 현재 코드의 최초 손실과 기존
실험 이력을 계속 구분한다. 자원 관측은 테스트 후 GPU0MiB/41°C, 여유 RAM19.80GiB였다.
