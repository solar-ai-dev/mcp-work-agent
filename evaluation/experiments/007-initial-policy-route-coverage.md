# 007. 초기 Query의 필수 정책 Route 보존 후보

기준 SHA `547732ad`, corpus `canonical92-v8-5a49aa00-ecf32ffc82`.
006의 현재 RU→Retrieval 합성 연결에서 `021` 첫 Query는 정책 충돌 확인의
`CALENDAR_EVENT` Route를 누락했다. Sufficiency 첫 출력은 `SUFFICIENT`였으나
기존 안전 Guard가 `CONTEXT_BLOCKED`로 막았다. 이는 schema-valid와 semantic-valid를
구분해야 하는 사례다. 05 `CTX-003`의 필수 Policy Precondition Route 보존을
초기 Query 출력 계약에 결합하면 여러 복합 요청에서 같은 누락을 줄일 수 있다는
가설을 검증한다. 새 Policy Route나 사용자 의미를 만들지 않는다.

첫 후보는 frozen Route의 `required=true`, `POLICY_*` reason, 실행 가능 READ를
동시에 만족하는 Route ID만 동적 Query schema의 배열 포함 조건과 round
validator에 제공했다. 다른 business Route는 강제하지 않는다. 단독 Calendar/Task
정책 deterministic path, 일반 다중 읽기, optional/access-only route, follow-up을
반례·기존 성공으로 본다. 단일 실패 문구에 대한 Prompt 규칙은 추가하지 않는다.

검증 순서는 계약 단위 테스트 → 저장 Node 입력 소규모 replay → 현재 RU/Route와
연결된 `021/028`의 synthetic Provider READ 비교다. 실제 Provider, WRITE, Planning은
여기서 실행하지 않는다. 첫 Query의 정책 Route 포함, first-call semantic valid,
revision 횟수, Evidence·Sufficiency 종료, LLM 호출·토큰·지연과 비정책 Route의
새 과잉 선택을 별도 기록한다. 후보가 schema-only 성공 또는 다른 의미 회귀만
만들면 채택하지 않는다. 동일 입력의 재실행 변동은 모든 Trial을 보존하고 PASS만
선택하지 않는다.

| 실패 유형 | 시도 방법 | 조건·근거 | 결과·회귀 | 판단 | 재시도 조건 |
| --- | --- | --- | --- | --- | --- |
| 초기 정책 READ Route 누락 | 동적 Schema 배열 포함 강제 | 006의 `021`, 05 `CTX-003` | 021/028 모두 schema repair 실패, 2 dispatch씩 | 기각 | 모델·Schema 복구 경계가 달라진 경우에만 |
| 초기 정책 READ Route 누락 | frozen Policy ID 투영 + round 검증 | 같은 입력·계약 | 021/028 첫 호출·revision 모두 한 필수 Route 누락, READ 0 | 기각 | 입력 표현·모델 경계가 달라질 때만 |
| 초기 정책 READ Route 누락 | 검증된 값으로 확정되는 pre-read만 구성 | frozen Policy·operation·container·period | 021/028 두 반복 모두 Work Analysis 전달, 014 유지·015 비정책 차단 유지 | 제한 채택 | 더 넓은 Node 분포·실제 Provider 검증 |

## 후보 A: 동적 Schema 강제 — 기각

계약 단위 테스트와 Retrieval 582개 테스트는 통과했다. 하지만 `021/028` 현재
RU→Retrieval 합성 연결에서 로컬 모델은 두 건 모두 필수 Policy Route를 포함한
JSON을 생성·복구하지 못했다. 각 2회 실제 Provider dispatch 후
`LLMInvocationError(schema repair did not produce a valid payload)`로 끝나
Query/Evidence가 0개다. 이는 첫 호출 semantic-valid 증가가 아니라 더 앞선
생성 실패 회귀다. 원시 결과는
`evaluation/results/request-to-evidence-policy-route-core021-028-20260916/`.
이 schema 강제는 제품 코드에서 제거한다.

## 후보 B: bounded 입력 투영 + 기존 round validator

같은 frozen Policy Route ID만 초기 Prompt 입력의
`required_policy_route_ids`로 전달한다. 동적 Schema는 기존 형태를 유지하고,
누락 시 기존 semantic revision 경계에서 검증한다. 추가 State나 Policy 판정은
없다. 021/028을 같은 조건으로 한 번씩 비교하고, 실패와 dispatch를 포함해
기록한다. 성공하더라도 non-policy Route 선택 및 Evidence 후단은 별도 평가다.

첫 시험은 Prompt input allowlist 미반영으로 두 건 모두 즉시
`unknown Product Prompt fields`가 났다(각 dispatch 1, LLM 결과 0).
이는 성능 Trial이 아니라 계약 오류로 분리했다. 계약·manifest를 정합화한 뒤
사전 고정한 두 건을 재실행했으나, 두 건 모두 첫 Query와 revision에 같은 정책
Route가 빠졌다(각 dispatch 2, Query 2회, READ 0). 이 방식을 더 반복하지 않고
활성 제품 코드·Prompt에서 제거한다. 원시 결과는 각각
`evaluation/results/request-to-evidence-policy-projection-core021-028-20260916/`와
`evaluation/results/request-to-evidence-policy-projection-contract-core021-028-20260916/`에
남긴다.

## 후보 C: 확정된 정책 pre-read의 결정적 합성

새 Policy Route를 추론하거나 비정책 Source를 강제하지 않는다. 기존 Calendar 충돌·
Task 중복 정책의 frozen required Route 중 현재 validated container와 route-bound 기간으로
READ의 operation·scope를 모두 확정할 수 있는 것만 LLM Query에 누락됐을 때
구성한다. 불확정 기간·대상·복수 operation은 구성하지 않고 기존 Guard가 막는다.
이 방법이 연결을 복구하더라도 LLM의 첫 semantic-valid 출력을 성공으로
재분류하지 않는다. `LLM omission → deterministic policy composition`을 별도
회복 유형으로 센다. 반례는 비정책 route, optional policy, 기간 불명확 Calendar,
이미 포함된 정책 route, follow-up이고, 기존 성공 014를 보존한다.

### 결과와 경계

두 번의 021/028 현재 RU→Tool Route→Retrieval 합성 연결에서 모두
`WORK_ANALYSIS`로 전달됐다. 각 첫 Trial의 021/028 Evidence는 6/4건,
반복 Trial은 6/5건이다. Calendar·Event·FreeBusy 정책 Route는 모두
`COMPLETE`였고, 실제 Connector READ는 첫 Trial 6/5회, 반복 6/6회였다.
각 Case의 Retrieval LLM 호출·Provider dispatch는 3회씩이며 revision은
없다. 첫 Trial의 첫 Query 출력 route 수는 021=5, 028=4였으나 최종 READ는
각 6/5개 Route였다. 누락된 policy pre-read가 합성된 결과이지 LLM 첫 출력이
정확해진 결과가 아니다. 반복 Trial의 첫 Query route 수는 6/5로 달라져
모델 출력 변동도 남아 있다. Output의 Route ID별 의미 판정은 이 기록만으로
확정하지 않으며 first-call semantic-valid rate 개선을 주장하지 않는다.

대조 014는 이전과 동일하게 Evidence 2건을 `SOLUTION_PLANNING`으로 전달했다
(Retrieval LLM 1회). 015는 Task business Route가 미시도여서 여전히
`TOOL_ROUTE`로 돌아갔다(LLM 3회). 정책 합성은 비정책 Source 선택 결함을
가리지 않는다. 021/028의 첫 Trial Retrieval input/output token은 각각
25,555/1,941와 22,492/1,436, 지연은 54.6초/41.8초였다. Baseline의
21,624/1,231·42.4초와 21,322/1,307·44.4초보다 READ와 token이 늘어난
것은 필요한 정책 조회를 실제 수행했기 때문이다. 비용 개선으로 해석하지 않는다.

관련 Retrieval·Prompt·Graph 계약 633개 테스트 통과. 실제 Provider READ,
Work Analysis 이후 Planning·Review, WRITE preview·승인·실행, Stress/Holdout,
Core 전체 60의 반복 평가는 아직 하지 않았다. 이 단계는 구조적 안전 누락의
**제한 채택**이지 전 노드 안정화 완료가 아니다. 원시 결과는
`evaluation/results/request-to-evidence-policy-composition-core021-028-20260916/`,
`request-to-evidence-policy-composition-repeat-core021-028-20260916/`,
`request-to-evidence-policy-composition-core014-015-20260916/`에 있으며 ignore 규약상
원격에는 이 요약만 남는다.
