# 067–069 #286 자율 진행 checkpoint — 전체 미완료

이 구간 시작 HEAD `ba699074535926a509b22913da04f629350d8b9e`.
Product source/active Prompt 변경0. 이전 채택 Query ref 수정 `b7c449fa`의 실제 모델 gate를
닫았으며, 두 신규 RU/Planning 진단은 채택 근거를 얻지 못했다. Issue 본문/완료 상태는 바꾸지 않는다.

| Issue / 실행 | 확인 결과 | 결정·남은 문제 |
| --- | --- | --- |
| #287→#290,067 actual MainGraph CORE005 고정1회 | snapshot Task READ1, 답변 생성. 그러나 CREATE 금지 누락·INCOMPLETE 필터 발명·needsAction을 진행 중으로 답함 | persisted COMPLETED≠업무 PASS. 답변 PARTIAL이며 RU 의미 실패 별도 유지. Query LLM0이므로 exact-ref 수정 증거로 쓰지 않음 |
| #287,067 Goal UUID/time 교차2회 | 원문·Work·Provider identity·Prompt 동일. READ 목표는 유지하지만 실행값/search 슬롯 오염 지속 | 메타데이터 변경을 Product에 적용하지 않음. 구조 VALID와 의미 성공 분리 |
| #300,068 completion fact 고정3회 | actual wire에 incomplete 전달돼도 CORE005 PARTIAL 유지. completed control PASS→PASS | 효능 REJECT. Prompt 후처리/상태 규칙 추가0 |
| #290,069 실제 frozen Query FIRST1회 | typed exact ref 생성, actual validator/build_query 통과, revision0 | 기존 Product 수정 유지. 단발 gate PASS이지 전체Query/업무/반복 안정성 PASS 아님 |

이번 신규 모델 총15calls(9+2+3+1), input51,228/output1,602 tokens,
API reported 합121,892ms. 서로 다른 owner·입력·실행 목적의 **사용량 합**일 뿐 품질 분모나
전후 latency 효과가 아니다. 과거 응답 재사용 비용은 합산하지 않았다. usage 누락0.
외부 Provider READ/WRITE0, 로컬 snapshot READ1, 승인0, rerun-to-pass0.
상세 SHA/Prompt/hash/각 비용·회귀는067/068/069 개별 결과 문서와 ignore된 raw를 따른다.

## 현재 유지하는 것과 채택하지 않은 것

- Work/item binding, frozen capability, Approval/Execution/Verification 계약 유지.
- Query generation Schema가 기존 identity validator authority와 같은 exact ref 집합을 사용한다.
  native ID 추정/validator 완화/round·retry 확대가 아니다.
- Goal metadata alias, optional completion-fact input, 추가 Prompt patch는 Product에 적용하지 않는다.
  비활성 후보와 실패 raw를 보존한다. Canonical05/15의 evaluation-only fact 실험 설명은
  개발 후보 경계이며 Production input의 활성화가 아니다.
- notes/identity 요구를 없애 Task formatter로 우회하지 않는다. READ용 정보와 사용자 답변
  필드는 같은 개념이 아니며 completeness 검사를 약화하면064의 누락 결함을 되살린다.

## 남은 실패와 현재 탐색 경계

Source 누락/오선택, Goal constraint 오염, 미요청 Output WRITE, 금지/status 의미 변형,
compose의 completion enum 과잉해석이 남는다. 원문·확정값이 실제 입력에 있는데 FIRST부터
잘못 나온 실패와 deterministic 전달 결함을 구분했다.

독립 코드/raw audit에서도 새로운 producer→consumer 손실은 확인하지 못했다.
기존 Source/Output/Goal 표현·입력·owner·sampling·runtime 후보의 회귀 기록을 재검토했고,
이번 UUID/time 교차 및 typed fact 진단도 기존 안정성 문제를 해결하지 못했다.
동일 fact를 다른 위치에 추가하거나 문구만 바꾸는 다음 호출에는 새 인과 근거가 없다.
따라서 지금 확보한 근거에서는 사용자 종료 조건4의 무근거 추가 탐색 경계로 기록한다.
이는 모든 구조 가능성의 수학적 소진, 모델 한계, 학습 필요성 또는 #286 완료 판정이 아니다.

재개 근거는 실제로 누락된 입력·불일치한 contract, 다른 책임 배치가 오류를 만드는 구체적인
반례, 또는 독립 검증 가능한 모델/학습 계획이다. 새로운 raw의 같은 실패만으로 같은 방식을
다시 돌리지 않는다. 대형 모델 download/training, 비용·전송 경계 변경은 임의로 시작하지 않았다.

## 검증 범위

- 069 직접/인접95 PASS, Ruff와 새 runner mypy PASS. 새 test scoped mypy PASS;
  import 추적 시 기존 fake helper의 타입 오류2개는 미수정이며 전체 mypy PASS가 아니다.
- 현재 Product SHA의 Canonical92 전체 성적 **미측정**.061/062 수치를 승계하지 않는다.
- 아직 Retrieval→Work Analysis→Planning→Review 전반의 반복 안정성과 승인 후 실제
  Execution/Verification/Recovery, Live Provider 업무 성공, Release activation은 미검증이다.
- 실패를 성공으로 재분류하지 않았고, Issue별 단발 성공을 Epic 완료로 합산하지 않았다.
- 모델 동시1, 생성 중 pytest/코드편집0, 작은 직렬 검증만 수행했다. 자원 압박이나 OOM 때문에
  실패한 것으로 오인하지 않는다. 원인이 이미 확보돼 LangSmith용 추가 Run은 만들지 않았다.

검증된 결과 댓글: [#290](https://github.com/solar-ai-dev/mcp-work-agent/issues/290#issuecomment-5874966945),
[#286](https://github.com/solar-ai-dev/mcp-work-agent/issues/286#issuecomment-5874967321).
상세 raw는 기존 ignore 경계에 있고, 공개 가능한 결론·hash·재현 도구는 commit으로 보존한다.
