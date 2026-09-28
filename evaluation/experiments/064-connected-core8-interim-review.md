# 064 — Connected Core8 T1 중간 의미 검수

## 범위와 근거

`064-connected-core8-review-criteria.md`와 현재 Canonical v8을 적용한다. 검수 시점의
raw만 읽었으며, 질문·Gold·제품·Prompt·runner·원시 결과를 수정하거나 모델을 추가 호출하지 않았다.

- HEAD: `c8708b1d95298e934dfa9ad7cc8ca5d5d7f611cf`
- Trial: `f2aa85d4-b89a-4b77-90d3-d532f2c78b59`, Case/arm당 사전 고정 1회.
- 원본: `evaluation/results/064-connected-core8-t1/`.
- 완료된 paired Case: **005/009/017/019, 4개**. 023은 Production만 완료했고 후보는
  Source dispatch 도중 세션이 중단됐다. 025/035/059는 미실행이다.
- `COMPONENT_RETURNED`는 RU → Tool Route callback이 반환됐다는 의미다.
  실제 Retrieval/Planning/Preview/승인/실행/업무 성공 판정이 아니다. 두 arm 모두 관련
  실제 Provider READ/WRITE를 실행하지 않는다.
- 같은 SHA·Dataset·snapshot·model digest·seed·사례별 기준시각을 사용했다. Production의
  Goal0.1/별도 Output0과 후보 joint Goal/Output0은 의도적으로 다르므로, 순수 호출 수만의
  인과 실험이나 동일 Prompt 비교라고 하지 않는다. selected Provider identity는 같지만
  current-Run resource_ref_id 등 실행 identity는 arm마다 다르다.

기록된 모든 **53개 dispatch의 actual wire hash**가 현재 결속 코드의 registry/assembler와
동일 input/Schema/PromptRef/options로 메모리에서 재구성한 payload와 일치했다.
52개 응답이 반환됐고 1개는 응답 미관측이다. Product Prompt처럼 위장된 후보 호출이나
실행 도중 Prompt 변경의 증거는 없다. 재구성은 네트워크/모델 호출 없이 수행했다.

## Case별 첫 divergence와 연결 결과

| Case | Production | Goal/Output 후보 | 구조/연결과 의미의 구분 |
| --- | --- | --- | --- |
| 005 | **FAIL** — Goal은 상태·기한 READ이고 CREATE 금지도 맞았지만 call5 Output FIRST가 `TASK/UPDATE + GMAIL_MESSAGE/SEND`를 추가. 실제 ACTION Route까지 전달 | **FAIL** — Output 없음/ANSWER로 개선. 그러나 call3 prohibition FIRST가 명시 CREATE 금지를 NOT_FORBIDDEN으로 누락. call5 status FIRST는 단순 상태 질문을 `INCOMPLETE` 필터로 추가 | 두 arm 모두 구조 통과/Route 반환. 후보의 WRITE 제거 성과와 typed 금지·상태 필터 회귀를 따로 기록. 외부 WRITE가 0이라고 금지 보존 PASS를 주지 않음 |
| 009 | **FAIL** — call3에서 원문에 없는 명시 SEND 금지를 만들고, call4 Source에서 Task를 NOT_REQUIRED로 누락. call5 Output이 Draft+Task CREATE를 추가 | **FAIL** — call2 joint FIRST의 완료조건에 `메일 초안과 작업 항목이 생성되거나 요약되어 제공됨`을 추가. 실제 Output은 빈 목록/ANSWER이며 Source는 Thread+Task로 개선 | 후보 Route는 필요한 두 업무 Source와 READ binding을 보존했지만 완료조건의 생성 허용·요약 대안이 사용자 READ와 모순돼 전체 의미 PASS/PARTIAL로 숨기지 않음. Production Task Route는 잘못된 CREATE의 중복검사 Policy에서 생겼으므로 Task 업무 근거 보존 증거가 아님 |
| 017 | **FAIL(구조 binding)** — call1 Work FIRST가 원문 공백을 바꿔 exact span validator 거절 | **FAIL(같은 구조 binding)** — call1 동일 결과/거절. joint Goal 미실행 | 한 업무로 본 것이 오류가 아님. 복사 문자열이 `8월 12일`→`8 월 12 일`, 주소 뒤 `에`→` 에`로 달라져 upstream에서 중단. 의미상 같은 문장의 재생성/원문 결속 계약 문제이며 Tool/Source/Output 품질 비교 불가 |
| 019 | **FAIL** — call2 Goal 완료조건에 `고객에게 워크숍 일정 안내 메일이 발송된다`가 추가. typed Output은 요청대로 Event CREATE+Draft CREATE | **PARTIAL** — call2 Goal/Output은 Event+Draft 준비와 상대시간을 보존. call4 Source가 CALENDAR에 Event facts를 요구하고, 새 Draft 준비에 기존 `GMAIL_DRAFT/SINGULAR`를 REQUIRED로 둠 | 두 arm 모두 관련 Calendar READ Route를 만든 뒤 다음 Retrieval에 넘김. 이 단계에서 시간 확인이 없다는 이유로 FAIL하지 않음. 후보 Policy Event/Freebusy Route가 실제로 존재하므로 단순 CALENDAR 이름 차이로 조회 불가능을 단정하지 않되 Source 사실 소유 불일치는 남김 |
| 023 | **FAIL** — mail+Task Source와 8월8일10:00/30분은 보존. call5 Output FIRST가 요청한 Event 외에 Draft CREATE를 추가 | **미완료/미채점** — 반환된 joint FIRST는 Event만 CREATE이고 30분/시각을 보존. call4 Source는 dispatch 시작 이후 응답 없음 | Production Route에 추가 Draft가 확정 전달됨. 후보의 앞단 Output 개선 관측만 보존하고 Source/정규화/Route 성공으로 확대하지 않음 |

완료된 동일 4 Case만 집계하면 Production **0 PASS / 0 PARTIAL / 4 FAIL**, 후보
**0 PASS / 1 PARTIAL / 3 FAIL**다. 이는 위의 구체적인 잔여 의미·binding 실패를 포함하는
보수적 RU/Route 판정이지 Canonical92 점수나 최종 업무 성공률이 아니다. 나머지 4 Case를
실패/성공으로 채우지 않는다. 023 Production 단독 FAIL은 이 paired 분모와 분리한다.

### 중요한 원인 구분

**005의 Output 자체 오류:** 실제 Output 입력은 올바른 READ Goal, `새로운 작업을 생성하지
않는다` 완료조건, 원문 전체와 CREATE FORBIDDEN을 받았다. UPDATE/SEND는 이 owner FIRST에서
처음 생성됐다. 앞 Goal이 이미 WRITE라고 말했기 때문이라고 설명할 수 없다. 후보는 그
재해석을 제거했으나 prohibition/status owner 입력과 출력이 달라져 부분 의미 회귀가 생겼다.
status의 `source_text`가 원문 exact span인 것은 맞지만, 그 문장이 미완료만 조회하라는 의미는
아니다. 구조 provenance 검증 통과를 status 의미 정확성으로 바꾸지 않는다.

**009의 Goal 오염과 Source 복원:** 후보의 `requested_outputs=[]/ANSWER_ONLY`는 올바르고
실제 Output도 바뀌지 않았다. 하지만 같은 joint 응답 내부의 완료조건은 Draft/Task 생성도
충족 방법으로 열어 놓았다. 이는 아직 downstream 실행을 유발한 사실은 아니지만 확정된
State에 남은 요청 오염이다. Production의 Task READ는 Policy 중복 검사 Route뿐이며,
`resource_responsibilities.source_reads`에서 필요한 Task 상태 정보가 사라진 것을 회복했다고
볼 수 없다. 후보는 Task `completion_status` 등 요구와 REQUESTED_INPUT Route를 실제 보존했다.

**017의 exact provenance 병목:** 두 arm의 Work 응답은 동일하고 JSON Schema는 통과했다.
그 뒤 `requested work span must bind exactly once to current user request:
work_units[0].request_spans[0]`로 ValueError가 발생했다. repair/semantic revision 0이며
시간 상한이나 Source 추론 실패가 아니다. 공백 변경 때문에 Graph가 의미상 타당한 단일
업무도 후속 owner에 전달하지 못한 것이 최초 실패 경계다. exact provenance를 완화하거나
코드가 문장을 추정 매칭한 결과는 이번 검수에 없다.

**019의 관측 시점:** Event가 “생성된다”는 completion condition은 승인 이후 달성할 목표를
기술한 것이며 현재 생성 완료라는 주장과 다르다. 후보를 이 이유로 overclaim 처리하지 않는다.
원문의 상대시간은 Goal/Work에 보존되고 임의 duration/시작시각은 추가되지 않았다. 한 Work가
두 요청 결과를 함께 표현한 것도 허용한다. 다만 Source FIRST가 요구한 `event_identity/start/end`
는 입력 Registry에서 CALENDAR_EVENT의 사실이고 CALENDAR 목록 자체의 사실은 아니다. 후보
Source의 실제 입력 Goal은 원문/빈 완료조건 projection이므로 이것을 joint의 생성 완료조건
문구가 그대로 전해진 결과라고 단정할 수도 없다. Policy는 Event/Freebusy 접근을 보충하지만
기존 Draft REQUIRED가 필요한지/없으면 어떻게 되는지는 아직 조회 전이라 미검증이다.

**023의 시간:** 실제 `run_reference_time`은 2026-08-07T09:00:00+09:00이고, 요청한
2026-08-08 10:00와 30분을 보존했다. 날짜가 주말이어도 이번 단계에서 임의 변경하지 않았다.
근무정책 확인이나 실제 availability 검증은 범위 밖이다. 후보 Goal의 추가 description·date
표현은 관측만 기록하며, 응답 없는 Source 이후의 의미를 추정하지 않는다.

## 비용·중단 기록

| Case | Production: calls / 입력 / 출력 / LLM ms | 후보: calls / 입력 / 출력 / LLM ms |
| --- | --- | --- |
| 005 | 7 / 18,168 / 556 / 30,139 | 6 / 15,316 / 641 / 31,211 |
| 009 | 7 / 16,285 / 514 / 28,152 | 6 / 14,623 / 727 / 33,317 |
| 017 | 1 / 764 / 83 / 3,459 | 1 / 764 / 83 / 3,114 |
| 019 | 7 / 18,377 / 652 / 33,970 | 6 / 15,933 / 850 / 38,151 |
| 023 | 8 / 22,898 / 878 / 44,631 | **dispatch 4, 반환 3** / **관측 6,186 / 714 / 27,498** |

완료된 paired4 합계: Production **22 calls / 53,594 in / 1,805 out / 95,720ms**,
후보 **19 calls / 46,636 in / 2,301 out / 105,793ms**. 후보가 3호출·6,958입력 토큰을
줄였지만 출력은 496토큰 늘고 이 단발 관측 지연은 10,073ms 길어졌다. 순차 실행·warm/cache
및 달라진 응답을 통제한 통계가 아니므로 속도 개선이라고 주장하지 않는다. Tool 선택 LLM은
0회이며 Registry 단일 후보 선택/Route 구성에 Provider 실행은 없다.

완료된 9 arm은 schema repair0, semantic revision0, usage 누락0이다. 023 후보는
`calls.json`에 Source의 `DISPATCH_STARTED`, wire_request_count1, 응답·usage·latency 부재가
남아 있다. `raw.json`은 시작 시점 RUNNING/metrics0 snapshot이므로 비용0의 근거가 아니다.
해당 arm의 `missing_usage_calls=1`을 유지하고, 알려진 비용은 반환된 3회분의 하한으로 표시한다.
총 dispatch53/반환52, 관측 129,314입력·5,698출력·273,642ms에 미관측 1회가 별도로 있다.
중단을 모델 timeout/semantic FAIL로 재분류하지 않으며 같은 Trial을 성공시키려고 덮어쓰지 않는다.

## 판단과 다음 책임 경계

- joint authority가 불필요 WRITE Route를 줄이는 근거는 005/009에서 확인됐고 023 앞단에서도
  관측됐다. 그러나 전체 의미 성공이나 반복 안정성은 아직 아니다.
- 기존 성공 전체가 보존됐다는 주장은 불가능하다. 특히 005의 명시 CREATE 금지와 status 필터는
  Production 대비 회귀이고, 019의 Source 표현/기존 Draft 의존도 새 잔여 문제다.
- Work exact span 재생성/결속, 단일 응답 안 Goal 완료조건과 Output의 모순, 금지·status owner의
  원문 의미 선택, Source Resource와 사실 소유의 불일치는 서로 다른 최초 실패군이다.
  마지막 Route 상태만 바꾸거나 후보 Prompt에 Case별 규칙을 덧붙일 근거가 아니다.
- **Production 미채택.** 이 문서는 완료 부분의 수평 진단 기록이며 이후 실험/계약 변경을
  자동 승인하거나 전체8/Canonical92/최종 workflow 성적을 대체하지 않는다.

## 재현 근거 hash

SHA256는 별도 표기가 없는 한 파일 bytes 기준이다.

- plan.json: `be5416a01d18e4ac8bf03e374e565e12669d35dfb0b440c80c7d3a834e1f4d02`
- raw의 plan_sha256은 JSON object hash
  `4a74c9704c0e3f0fd3b9ca1abf3f11aa361f5e332c1f2309bf205bcde60545fb`이며 10/10 일치.
- 완료9행 summary.json: `bd8f211ec898dcc53a325532d72971b6fa724006a804d3ee460775e91440d2bb`.
  각 행의 raw hash는 실제 파일과 모두 일치하며 raw의 UNREVIEWED 표시는 변경하지 않았다.
- 미완료 023 후보 raw.json: `7be2f3abe017adcf377e8f258e3020a1718ecb97b15495d1540318932768c581`.
- 미완료 023 후보 calls.json: `3f8262dcdd3d9900ebe5f1bebbdbebb25605cd8657346517dbb392e523449cd2`.
- 사전 의미 기준: `e047988bc7ac4fa49771f9c500af26815a59e8d94f98871e135ef3fc3fdfa381`.

검수 변경은 이 Markdown 한 파일뿐이며, 모델/Provider 추가 실행·제품 수정·commit은 0이다.

## Continuation — 미실행 025/035/059의 양 arm 완료

별도 결과 `evaluation/results/064-connected-core8-continuation-t1/`를 같은 사전 기준으로
검수했다. HEAD는 `1e66bc3aece7929b83c4a8ea60ad7bbe06442b5d`, Trial은
`7c761c4f-bb45-4b29-9e7e-f8111c155025`다. 이전 `c8708b1d`와 **SHA는 다르다**.
그러나 plan의 Product tree·Prompt tree·Registry·Dataset·snapshot·Python·모델 digest·runtime·
예산·사례별 기준시각/선택/fixture binding은 모두 동일하다. dependency 중 달라진 것은
미실행 항목만 별도 디렉터리에 이어 실행하는 `evaluate_snapshot_request_tool_route.py`뿐이다.
새 Product 후보·Prompt·sampling 실험을 같은 조건으로 숨겨 합친 것이 아니다.

기존 10 arm의 raw/calls **20개 파일 hash가 continuation 시작 시 기록과 그대로 일치**했다.
005/009/017/019 및 023 Production을 재실행하지 않았고, 중단된 023 후보도 재실행·덮어쓰기
없이 미채점으로 유지했다. 새 6 arm의 **29/29 actual wire hash** 역시 결속된 assembler/
원 input/Schema/PromptRef/options로 재조립하여 일치했다. 이 검수의 재조립은 모델 호출이 아니다.

### 새 3 Case의 의미 검수

| Case | Production | Goal/Output 후보 | 최초 경계와 실제 Route |
| --- | --- | --- | --- |
| 025 | **PASS(RU/Route 범위)** — mail+Task 근거, 오늘16:00/60분, Event CREATE를 보존 | **FAIL / 기존 성공 회귀** — call4 Source FIRST에서 메일을 GMAIL_DRAFT로 고르고 GMAIL_THREAD/MESSAGE와 TASK를 NOT_REQUIRED로 만듦 | Production은 Thread+Task 업무 Source와 Calendar 충돌검사 Route를 모두 구성. 후보는 Draft+TaskList identity만 요구하고 메일 Thread/Message 접근 Route가 없음. Calendar Event/Freebusy Policy Route는 유지되나 메일 근거를 회복하지 못함 |
| 035 | **FAIL(구조 binding)** | **FAIL(동일 구조 binding)** | 양쪽 call1 Work FIRST에서 `8월 10일까지`를 `8 월 10 일까지`로 재생성해 exact span 결속 거절. Goal/Source/Output/Route 이전 중단. 017과 같은 failure family |
| 059 | **FAIL** — call5 Output FIRST가 요청한 SEND 외에 독립 GMAIL_DRAFT CREATE를 추가 | **FAIL** — SEND 하나로 Output은 개선했지만 call2 joint 완료조건을 `생성된 메시지가 사용자의收件함으로 전송된다`로 만들어 답장 대상을 사용자 수신함으로 변형 | Production은 SEND+Draft CREATE 두 Output Route, 후보는 SEND 한 Route. 후보의 Thread/Message Source 접근은 있으나 기존 Draft까지 SINGULAR REQUIRED로 추가. 실제 recipient/Reply payload는 아직 Planning 전이라 미검증 |

**025에서 허용한 해석과 실제 누락:** 양 arm 모두 2026-08-07T09:00:00+09:00 기준을 받아
오늘16:00/60분이라는 사용자 시각을 Goal에 보존했다. 요청받은 새 Event에 제안한
`Echo 약관 메일 검토 작업` 제목·설명은 타당한 작성값이며, 원문에서 exact title을 지정한
것처럼 다루지 않았다는 이유만으로 이 구간을 실패 처리하지 않는다. Production 완료조건의
`work-1에 할당`은 불필요한 내부 표현이지만 실제 다른 사용자/외부 assignee 지정은 없고
typed Work binding이 일관되므로 관측되지 않은 업무 변경으로 과대 판정하지 않는다.
최종 Event 시간창·Payload·근무정책 판단까지 PASS라고 확장하지 않는다.

후보의 Task Route 자체는 TaskList에서 `RETRIEVAL_TASK_DETAIL`로 보충됐지만, Source의
`required_information`에는 Task의 상태·notes·due가 사라지고 list identity만 남았다.
이를 필요한 Task 근거 요구가 완전히 보존된 것으로 보지 않는다. 더 명백하게는 Echo의
실제 mail을 읽을 Thread/Message Route가 없고 Draft만 남았다. 이 실패는 Calendar를
Source item으로 직접 고르지 않았다는 이유나 Tool 순서 차이에 따른 판정이 아니다.
Task/메일 근거와 Output/time은 분리해 평가했다.

**035에서 아직 판단하지 않은 것:** 원문은 정상 Task CREATE와 mail 안 지시 무시를 포함하고
모델의 한 Work 문장도 그 의미를 유지했다. 실패는 분해 개수나 금지를 Task CREATE 금지로
오해해서가 아니라 문자열 공백 변경에 대한 provenance 거절이다. 제품의 fail-closed 경계를
우회한 재결속·repair·재실행은 없었다. 이후 공격 지시 취급/Calendar 조회/Task 생성안은 미검증이다.

**059에서 분리한 것:** SEND는 현재 v8 요청의 명시된 효과이며 legacy Draft UPDATE Smoke의
기준을 적용하지 않는다. Production Draft CREATE는 Provider의 내부 임시 구현 단계가 아니라
별도 사용자 결과로 확정된 Output Route이므로 추가 산출물 오류다. 후보의 `사용자의收件함`
표현은 단순 한글/한자 스타일 문제가 아니라 답장 상대를 바꾸는 완료조건이다. 이것이 현재
Run이 이미 메일을 보냈다는 주장이라는 뜻은 아니며, 실제 전송은 0이다. Source의 Draft
의존은 추가 우려로 기록하되, 잘못된 수신자 완료조건과 실제 WRITE payload 오류를 합치지 않는다.

### 완료 paired7 결과와 비용

023 후보 중단을 제외한 완료 paired Case는 **005/009/017/019/025/035/059, 7개**다.

| 평가 범위 | Production | joint 후보 |
| --- | --- | --- |
| RU/Route 의미 PASS / PARTIAL / FAIL | **1 / 0 / 6** | **0 / 1 / 6** |
| 실제 RU→Route component 반환 / Work binding 오류 | 5 / 2 | 5 / 2 |
| 불필요한 확정 WRITE Output Route | 5개: 005의 UPDATE+SEND, 009의 Draft+Task CREATE, 059의 Draft CREATE | 0개. 단 009의 생성 허용 완료조건과 059의 수신대상 오류는 여전히 FAIL |
| 실제 LLM calls / 입력 tokens / 출력 tokens | 38 / 92,974 / 3,324 | 32 / 78,628 / 3,930 |
| 실제 LLM 합계 latency | 178,026ms | 180,119ms |

기존 의미 PASS 025의 회귀 **1개**, 새 완전 PASS **0개**다. Source와 Outcome의 일부 개선을
무시하지 않되, 명시 금지 누락·상태 필터 발명·Source 오선택·완료조건 오염을 반영하면
현재 후보를 전체 의미 개선/Production 채택으로 결론낼 수 없다. 단일 Work가 두 결과를
함께 표현한 019는 허용했고 Work 개수 자체로 점수를 깎지 않았다. 실제 multi-Work 간
binding/Relation 품질은 이 단발 집합에서 충분히 관측되지 않았으며 별도 미검증이다.

추가 3 Case의 실제 비용:

| Case | Production: calls / 입력 / 출력 / LLM ms | 후보: calls / 입력 / 출력 / LLM ms |
| --- | --- | --- |
| 025 | 8 / 22,063 / 866 / 48,811 | 6 / 16,103 / 872 / 39,105 |
| 035 | 1 / 764 / 84 / 3,554 | 1 / 764 / 84 / 3,072 |
| 059 | 7 / 16,553 / 569 / 29,941 | 6 / 15,125 / 673 / 32,149 |

추가 29회는 모두 FIRST RETURNED, schema repair0/semantic revision0/usage 누락0이다.
조회·Tool 실행 전 종료하므로 Provider READ/WRITE/SEND와 승인0, rerun-to-pass0이다.
후보는 완료 paired7에서 6호출·14,346입력 토큰을 줄였지만 출력606토큰 증가 및 관측 지연
2,093ms 증가가 있다. 장비 warm/cache를 통제한 반복 latency 평가가 아니며 비용 감소와
업무 의미 성공을 혼동하지 않는다. 023의 독립 실패/중단 비용은 위 paired7 합계에 넣지 않았다.

**최종 비교 판단:** 현 형태의 joint 후보는 Production 미채택. Output 중복 재해석 제거는
유효한 근거로 보존하되, 025 Source 회귀와 009/059 완료조건 오염을 닫지 않은 채 채택하지
않는다. Work provenance의 exact 문자열 재생성 실패는 017/035에 걸친 독립 구조 병목이다.
이를 해소하기 위해 정상 공백 변형을 임의로 원문에 맞추거나 금지 validator를 약화할 근거는
없다. 다음 구조 선택은 이 failure family들을 별도로 다뤄야 한다. 이번 검수는 이미 끝난
Trial 기록만 이용했으며 새 Prompt 후보·모델 실행·Product 수정은 없다.

### Continuation 근거 hash

- plan bytes: `29b131bc6cdd7da9c018dfa8e17ac705d3cf0ebd31d72065b0ee7411eff2de10`
- plan object: `608123166cb3fcf9369dee8dd5f7ba76b43ffb6b5dfa0231293bccc8684ca0fc`
- summary bytes: `82c3a9ace1270eafb286c9c00e89c317e1e3398368eda331129c5cb8b44e0be3`
- continuation-observations bytes:
  `6f3262cd6290d79468b03d273f1b350ba69b660d0a693523c45f29344507f016`

| Case / arm | raw.json bytes SHA256 |
| --- | --- |
| 025 Production | `f8114fcc3eb32680271041657abc33fe0781805ceccc4845a6530c7add276e0e` |
| 025 candidate | `3cf2d715f3fe147ae7c8639afc88dbca09a0f900820350ef1b0d1ee2876f6b1b` |
| 035 Production | `997f30c3046f0f455f2f813d75edd4c706a6813318b4efe958fdea1f5897247a` |
| 035 candidate | `af3ebfbe1cb06366a49096d553a030323211cb45eb6490b924f8c2b175a55d24` |
| 059 Production | `5bf12cfd4ca9df59b5513edc263982c5f7385db44c7cd3ef1e84f3f69a8ff3e2` |
| 059 candidate | `3893cec435ca0b400a42c8890c0e1bcc466d357eea00cb590b05401dc8c45258` |

제품의 이후 수정 SHA를 이 실행 결과에 소급하지 않는다. raw/calls·Dataset·Gold는 불변이고
이 문서의 continuation section만 추가했다.
