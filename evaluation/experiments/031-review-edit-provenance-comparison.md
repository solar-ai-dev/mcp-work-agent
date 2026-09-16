# 031. Preview 수정의 이전값 provenance와 현재 요구 Projection

기준 SHA `4405f17d` (`4e66353c`에서 RECHECK 출력 모순만 막음), clean tree.
022의 B/C는 새 edit binding을 옛 constraint와 병렬 제공했고 D는 field 이름만
같으면 Intent constraint value를 교체했다. D가 title 오류를 없앴으나 근거
부족 허위 finding을 만들었으므로 제품 미채택이었다.

029의 격리 백엔드 023에서 Action `payload.title` 수정은 Domain Action과
checkpoint `__modify_review_changes__`에 남았다. resume의 Review 결과는
제목 오류가 아니라 Task 내용 EVIDENCE_GAP이었다. 수집된 Task 근거는
Task item이 아닌 Task list 제목뿐이어서 그 gap이 거짓이라고 단정할 수 없다.
같은 Run의 최초 Review는 이 근거로 PASS였다. 이는 title 보존과 외부
Evidence 충분성/안정성을 독립 축으로 검토할 새 근거다. 029의 Live BLOCKED를
022의 title 오류와 같은 실패로 계산하지 않는다.

## 사전 비교 조건

- 목적: 허용된 Preview 수정이 같은 Action의 현재 요구로 소비되고,
  잘못된 현재값은 발견하며, 무관 Action·조건은 유지되는지 확인.
- A는 현행 Review Goal 입력, B는 해당 Action의 수정 전 Planning argument
  값과 현재 edit path/value가 검증되고, RequestIntent constraint가 같은
  field 및 **정확한 이전값**으로 단 하나일 때만 그 옛 constraint를
  Review-only 현재 요구 Projection에서 비활성화한다. 현재값은 기존
  `user_action_modifications`로 계속 전달하고, 원본 Intent/원문/Evidence는
  수정·삭제하지 않는다. 불일치·다중 Action/constraint·provenance 있는
  값은 변경하지 않는다. 이는 022 D의 field-name-only 교체와 다른
  provenance 증명 조건이다.
- 저장된 023 Preview 수정과 정상 023/028, 합성 028 제목 수정,
  023 제목 수정값 불일치, 028 설명 수정 일치/불일치, 합성 메일 근거 부족
  023을 구분한다. 동일 Goal prompt source/output schema, qwen3.5:9b 고정
  digest/temp0/seed1729, 입력별 A/B 각 1회 최대 16 직렬 호출. 정상 2건은
  B가 A와 동일 입력이다. 모델 실패도 보존하고 재시도해 골라내지 않는다.
- 채택 후보 조건: 수정 일치 제목·설명의 허위 finding 감소, 불일치의 실제
  ISSUE 유지, 정상 Plan과 근거 부족 분류에서 새 회귀 없음. 첫 결과가
  유력하면 별도 사전 반복·compiled·Live 예산을 정한다. 반례가 나오면
  입력 책임과 Evidence 경계를 조사하며 제품 코드는 아직 바꾸지 않는다.
- Provider READ/WRITE 0, 전체 92 0. 029의 실제 Run은 다른 Evidence
  fingerprint이므로 이 Node 비교의 동일 입력 반복으로 취급하지 않는다.

첫 실행은 6개 완료 호출의 결과 기록 단계에서 평가 하네스의 존재하지 않는
`StructuredInferenceResultV1.attempts` 접근 오류를 발견해 중단했다.
여섯 호출은 실제로 진행됐으나 raw 결과가 기록되지 않아 **측정 불능**으로
남긴다(`evaluation/results/review-edit-provenance-20260917/invalid-harness.json`).
7번째 호출은 중단 당시 진행 중이어서 dispatch 완료 여부를 확정하지 않는다.
제품 실패나 성공으로 재분류하지 않는다. 필드 접근만 `fallback_reason`으로
고쳐 같은 계획 16개를 새 결과 파일에 실행하고, 총 호출 비용은 최소 6+16으로
분리한다. 측정 불능 호출을 성공 Trial로 덮어쓰지 않는다.

## 결과 — B 미채택

새 결과 `evaluation/results/review-edit-provenance-20260917/node-comparison.json`의
16/16은 structured output을 반환했고 직접 기록한 repair/첫 원출력은 없어
그 두 축을 성공으로 주장하지 않는다. 저장 023 제목 일치는 A의 허위 ISSUE
3개가 B에서 1개로 줄었으나 완전히 사라지지 않았다. 합성 028 제목은 1→0,
두 제목 불일치는 ISSUE를 유지했다. 정상 023/028은 각각 0→0이었다.
반면 다른 허용 field인 028 설명 수정 일치에서는 A가 ISSUE+CONFIRMATION
2개, B가 ISSUE+CONFIRMATION 두 개를 포함한 3개로 악화했다. 이는
실제 슬롯 선택이 이미 Plan에 있고 별도 공급업체 연락을 현재 일정 생성의
선행 질문으로 만드는 과잉 판단이었다. 설명 불일치는 A/B 모두 ISSUE를
냈지만 수정값 자체에 정확히 묶인 판단이라고 보기 어려웠다. 실제 메일
Evidence 부족 합성에서는 A/B 모두 올바른 EVIDENCE_GAP와 불필요한
“일정을 생성할까요?” CONFIRMATION을 함께 출력했다.

동일 A/B 8개씩 총 input tokens 84,738/84,604, output 2,691/2,302,
node 경과 합 77,384/61,417ms(단발, 안정적 latency 우위 아님).
022 D의 field-name-only 대체와 달리 이전 Action 값까지 검증해도
Goal inspector의 사용자 권위와 외부 Evidence 판단이 일관되지 않았다.
따라서 현 후보를 제품에 넣지 않는다. 029 실제 Live는 Task item 내용이
없어 EVIDENCE_GAP일 수 있는 별도 입력이며 이 비교의 회귀 분모에 넣지
않는다. 다음 후보는 같은 constraint 교체 문구를 반복하기보다 원문
Evidence의 역할 또는 inspector의 출력 책임 경계를 다시 본다.
