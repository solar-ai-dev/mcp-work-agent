# 013. Review 기준시각의 좁은 Projection 진단

기준 SHA `9440635a` + 011 Retrieval 후보. 012의 연결 Trial에서
`review.inspect_goal_and_evidence`는 028의 사용자 `내일`을 Gmail 수신일
2026-09-07에 결합해 2026-09-08이라고 오판했다. 실제 current-Run 시작은
2026-08-07이며 Planning의 2026-08-08은 그 기준에 맞는다. Review 첫 입력에는
`request_intent`의 상대 날짜, Evidence의 수신일, Plan은 있었지만 Run 기준시각은
없었다. 이는 State 부재가 아니라 consumer Projection 누락 후보이다.

입력 계약 후보는 이미 검증된 current-Run `run_budget.started_at_ms`를 기존
`project_run_reference_time`으로 Review의 goal/evidence inspector에만 제공한다.
제품 채택 시 DATE/TIME 제약이 없는 요청에는 이 시간 축을 활성화하지 않는다. Evidence
metadata 시각을 사용자 요청 시각으로 강제 바인딩하는 규칙이나 새 날짜 판정기는
추가하지 않는다. 06/15/Prompt input contract의 제품 변경은 비교 후 결정한다.

고정된 012의 Review 첫 Prompt input 023·028 각각에 대해 기준 A는 저장된 첫
structured output, 후보 B는 같은 input에 `run_reference_time`만 더해 같은
9B digest, temperature 0, seed 1729로 **각 1회** 호출한다. 새 Provider READ,
Work Analysis, Planning, WRITE는 실행하지 않는다. 023은 기존 성공 대조,
028은 적용 요청이다. B의 Schema 유효, 날짜 근거, 잘못된 EVIDENCE_GAP의 변화,
호출·토큰·지연·오류를 모두 기록한다. 첫 structured inference와 provider raw
completion은 구분한다. 단일 성공은 안정성 입증이 아니다. 입력 내용과 출력
상세는 ignored local result에만 보존한다.

## 결과·판정

후보용 Prompt input contract v2는 로컬 개발 비교에서만 사용했고, 제품
manifest·contract와 Review Node에는 채택하지 않았다. 저장된 A와 고정 입력 B를
대조한 결과는 다음과 같다.

| 입력 | A 첫 structured output | B 기준시각 추가 첫 structured output | B 호출 비용 |
| --- | --- | --- | --- |
| 023 | finding 0 | 생성 전 Preview를 ‘아직 미실행’ ISSUE/EVIDENCE_GAP로 오판, finding 2 | 10,990/845 tokens, 29.8초 |
| 028 | `내일=9/8` 오판 + 실제 내용 누락을 EVIDENCE_GAP로 오분류 | `내일=8/8`은 바로잡았지만 메일의 9/7 **수신일**을 지연 **발생일**로 묶어 시간 모순 ISSUE, finding 1 | 10,720/645 tokens, 20.2초 |

Schema는 둘 다 통과했다. 그러나 023 기존 성공을 깨고 028도 관계를 잘못
바꿨으므로 **후보 기각**이다. 단순 기준시각 Projection은 #2 입력 누락 일부를
해결했지만, metadata timestamp의 출처·대상 관계(#3)와 Preview/실행 상태
판단(#4)을 해결하지 못한다. 시간 필드를 추가할 때마다 다른 의미축 오판이
생기는 패턴을 피해야 한다. 다음 Review 개선은 023/028뿐 아니라 021과
후속·confirmation·revision 입력에 대해 날짜 역할과 계획/실행 단계를 좁은
typed State로 구별할 수 있는지 먼저 검토한다. 시각 단어 분기나 Case별 규칙은
재시도 조건이 아니다. 단일 후보 Trial은 안정성/전체 92/실제 Provider 근거가
아니다. 상세 입력·출력은 ignored `evaluation/results/review-reference-023-028-20260916/`
에만 있다.
