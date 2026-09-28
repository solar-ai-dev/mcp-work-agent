# 088 — 등록된 실제 Planning 연결: 구조8/8, 의미6 PASS / 0 PARTIAL / 2 FAIL

실행 SHA `daa9f78b` (Product repair 수정 `d9993905` 포함).
기존084 성공을 승계하지 않고 실제9B를 고정8회 새로 호출했다. **연결 구현은 검증됐지만
답변 후보의 의미 회귀로 Main 확장 gate는 통과하지 못했다.** Product Prompt는 미활성이다.

## 실제 답변과 최초 차이

| 입력·반복 | 결과 | 실제 관측·이유 |
| --- | --- | --- |
| CORE005 상태·기한만,2회 | FAIL2 | 미완료와2026-08-10은 정확하다. 그러나 요청하지 않은 제목·메모 원문도 추가했다. FIRST가 `title/status/due/notes` 네 필드를 선택했고 renderer는 그대로 전달했다. 명시 범위 위반을 schema 통과나 사실 정확성으로 PASS 처리하지 않는다. |
| 완료 상태·메모,2회 | PASS2 | completed 상태와 장비 수령 확인 메모를 보존했다. 추가 title은 이 요청에 금지되지 않은 맥락이다. PROSE 분기로 응답했다. |
| 메모 재작성·원문 인용 금지,2회 | PASS2 | 계정 발급/장비 수령을 확인 항목으로 재작성했다. 원문 문장을 인용하지 않았다. PROSE 분기를 유지했다. |
| Calendar 시간·장소,2회 | PASS2 | 원 Product composer에 위임했고 오전10~11시·한빛회의실을 보존했다. 085의 오후10~11시 회귀를 반복하지 않았다. |

모든 FIRST가 schema-valid이고 repair/revision0이다. 8개 모두 실제 compiled Planning의
AnswerDraft를 만들고 actual durable-fact Supervisor projection에서
`ANSWER_ONLY_RESPONSE_READY → RESPONSE_SYNTHESIS`로 갔다. 구조 성공은 의미 성공과 다르다.
동일seed 두 반복의 각 답변은 동일했다. 실패도 반복됐으므로 이를 전체 안정성으로 표현하지 않는다.

## 084와의 정확한 비교·다음 원인분리

같은3개 입력의 역사084는6 PASS, 새088은4 PASS/2 FAIL이다. 084의 raw를 재실행으로
표현하지 않는다. 양쪽 actual payload의 input·format/property order·model·think·options는
같지만 SYSTEM 조립과 USER body의 PromptRef version이 다르다.

- 084도 ROLE 뒤에 전체 입력을 SYSTEM에 넣고 USER input에 다시 넣었다. 따라서
  **새로운 입력 중복 때문에 회귀했다는 설명은 틀리다.** 중복 제거 재실험은 하지 않는다.
- 088은 실제 assembler의 Product-wide context와 입력 제목을 사용한다. body의
  `prompt_ref.prompt_version`도 `v1 → evaluation-answer-choice-connected-v088`로 바뀌었다.
- 최초 관측 오류는 compose FIRST의 field 선택이다. 입력·outline의 “상태와 기한만”은
  소실되지 않았다. renderer나 후속 normalizer가 title/notes를 추가한 것이 아니다.
- Source 수집 목록이 `USER_REQUIREMENT.required_information`에도 복제되는 현재 표현은
  부담 요인일 수 있지만, 084에도 같았다. 이번 회귀의 확정 원인으로 쓰지 않는다.

현재 판단은 **등록/handoff 개발 구조 채택, 이 assembly 조건의 의미 승격 기각**이다.
규칙·정답 schema·keyword 후처리를 추가하지 않는다. 준비된089 Main 실행은 아직 하지 않고,
공통 assembly 문맥과 version metadata를 각각 분리하는 작은090 비교로 이어간다.
Product 전체에서 공통 문맥을 삭제하거나 수집필드를 답변필드로 강제하는 결정은 하지 않았다.

## 함께 수정한 확정 Product 결함

실제 router 연결의 직접검사에서, PROSE answer 필드만 잘못됐는데 schema repair가 정상
출처 배열까지 삭제해도 허용되는 RED를 확인했다(최초21 PASS/1 FAIL).
`output_schema_validation._validate_one_of`가 이미 선언된 유일 branch의 세부 오류와
aggregate `$` 오류를 함께 보고해 repair membership 권한을 넓힌 것이 원인이다.

`d9993905`는 선언된 branch의 실제 field 오류만 보고한다. JSON 유효값·LLM 의미·Prompt는
바꾸지 않는다. branch 미확정/다중 일치의 union 오류와 실제 array cardinality repair는
유지한다. 정상 sibling 배열의 추가·삭제를 막는 top/nested 반례와 직접 router 경계를 검증했다.
이 **한 Product 수정은 채택**했으며 비활성 답변 후보와 구별한다.

## 검증·비용·제한

- 직접·인접332 tests PASS + runner 직접6 PASS = unique338 PASS. 후보22 검사는332에
  포함하므로 합산하지 않는다. 변경 파일 scoped Ruff/mypy PASS.
- full-import mypy는 기존 `evaluation/request_semantic_authority_candidate.py:843`의
  Mapping indexed assignment 오류1을 별도로 발견했다. 이번 변경 오류로 숨기거나 전체
  mypy PASS라고 보고하지 않는다. 변경 파일의 silent-import scope는 통과했다.
- fake gate1은8 RETURNED이나 합성6개가 route meta 부재로 RECOVERY였다. 이를 폐기하지
  않았다. 기존 Product Resource→Registry→finalize 함수로 synthetic freshness를 준비한
  fake gate2에서8/8 정상 Supervisor 전환, wire일치, dispatch ledger각1을 확인했다.
  모델 입력·업무 의미는 바꾸지 않았고 fake 모델 생성은0이다.
- actual8 FIRST: input24,466 / output1,082 tokens, reported49,878ms / wall57,063ms.
  usage 누락0. schema repair0, semantic revision0, actual budget ledger각1, NORMAL14/900000ms 유지.
- 모델 qwen3.5:9b Q4_K_M, exact digest
  `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`.
  Ollama0.34.0, ctx16384, think=false, seed20260923, temperature/presence override 미전송.
- GPU 한 모델/한 호출씩. 실제 중간 관측6383MiB/8188MiB, GPU66%,64°C.
  시작 여유RAM약19.4GiB. peak 수치라고 주장하지 않는다.
- Product/historical input/model/actual ordered wire 봉인 불변. Provider snapshot READ0,
  WRITE/SEND/거절된 WRITE 시도0. 승인0, rerun-to-pass0, Dataset/Gold 변경0.
- 실제 Main, public API, terminal intent/DB commit, durable budget CAS·schedule/claim/resume,
  Canonical92, Live Provider, Release activation은 이 결과로 검증하지 않았다.

## 재현 근거

- plan `evaluation/results/088-registered-answer-choice-plan/plan.json`, object hash
  `7314c45d81ccee68a1147e7648cef25beaa376a807d1f9329dff054a6a85d983`.
- actual raw `evaluation/results/088-registered-answer-choice-t1/raw.json`, SHA256
  `41e086022a73ae24405e886e466052c0d2a78371258d82aa7b652f31d2788d0c`.
- fake2 raw SHA256 `d5dcaaaf3527944e1aa9518a12ad26187b47c8aee315681245bd80ab799c54df`.
- 상세 원문/transport/DB는 local ignored results에 보존한다. 이 문서가 원격용 비민감 요약이다.

전체92의 새로운 점수나 전체 LangGraph 안정화 완료가 아니다. 이 결과와 미검증 범위를
보존하며 다음 원인분리를 계속한다.
