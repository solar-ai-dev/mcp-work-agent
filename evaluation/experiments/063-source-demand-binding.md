# 063 — Source demand → capability binding

## 사전 가설과 경계

기준 Product는 `cdbc23bb`이며 062 v4를 개선 출발점으로 사용한다.
현재 Source 입력의 goal은 `project_extractive_source_goal`에서 이미 원문으로
치환된다. 따라서 062의 '생성 Goal이 Source를 직접 축소했다'는 설명은 확정 원인이
아니다. CORE-025/027/058은 Route의 Task/Event 보강도 있으므로 Source 목록만으로
RU→Route 실패를 단정하지 않는다. 최종 업무 성공은 이번 범위가 아니다.

003의 constraints 제거/sparse Resource 목록과 037의 fact enum 결속은 필요한
item owner 누락으로 기각됐다. 단순 재시도하지 않는다. 새 후보는 Resource별
10개 yes/no 대신 **필요한 업무 정보 → 해당 정보의 Source ref** 순서로 작성한다.
Source ref는 현재 Registry READ 후보의 닫힌 집합이다. Source 의미를 validator가
발명하지 않으며, 모델이 고른 ref만 기존 Source decision에 결정적으로 투영한다.
v4의 Goal/모달리티/Output authority는 유지한다. 후보는 scripts의 개발 adapter이며
Product manifest/Prompt/State/Node/안전 계약을 활성화하지 않는다.

## 고정 진단

- Core 001/013/019/023/025/027/045/049: selected identity·기존 성공, Source 없음,
  관련 READ 후 확인, 복수 Source, 가용성, 다중 Output을 함께 포함한다.
- 기존 v4 raw의 **동일 Source owner 입력** 재사용. 우선 각 1회 신규 후보 호출.
  유력하면 동일 입력 1회 추가와 현재 v4 Source 1회 대조(총 최대 24 호출,
  각 schema repair 최대 1회 포함 시 48 dispatch)를 실행한다.
- 모델 qwen3.5:9b, digest 고정 확인, temperature 0, seed 20260923,
  think=false, num_ctx=16384. actual input/hash/첫 출력/repair/오류/호출 비용 보존.
- 첫 오류도 기록하며 rerun-to-pass 금지. 기존 성공 source 손실·불필요 source 증가가
  반복되면 전수 평가로 확장하지 않는다. 작은 변경마다 92개 실행 금지.
- node source 계약, RU→Route 연결, Retrieval 이후 업무 성공을 별도로 판정한다.
  Event와 FreeBusy 등 합리적 사실 접근 대안을 허용하되 명시적 Source 제외는 유지한다.
- Provider READ/WRITE/SEND=0. Dataset/Gold를 모델 입력에 넣지 않는다.

실제 결과와 다음 판단은 실행 후 아래에 추가한다.

## v6 판정과 다음 축 (실행 전 고정)

v6 첫 8건에서 Task를 Message/TaskList에 결속하거나 누락하는 동일 실패가 재발했다.
019는 source ref 중복으로 구조 실패다. 023/027의 Task 누락 회귀도 있어 v6는
REJECT, 반복/전수 실행하지 않는다. 003/037과 같은 Resource 선택 부담을 출력 순서만
바꿔 제거하지 못했다. 다음 v7은 **자료 필요 해석 → Source ref 결속**을 두 호출로
분리한다. 두 번째 호출은 need ID와 Source ref만 반환하며 정보/조건/WorkUnit을
재생성할 수 없다. 최초 해석에 Registry affordance를 넣지 않는다.

동일 8개 frozen 입력, 첫 Trial 각 2회 model call, 유력할 때만 반복/connected를
넓힌다. Source owner의 physical call 수 증가를 숨기지 않는다. Product budget·Prompt
activation은 바꾸지 않는 개발 구조 후보다. ambiguity/승인/WRITE는 계속 기존 owner다.

v7도 기각한다. 001은 추출한 기한/담당을 body의 업무 사실로 연결하지 못했고,
023/027은 최초 information needs가 원문의 메일·Task를 Calendar 뜻으로 바꿨다.
049는 세 자료를 하나의 need로 묶어 one-source-per-need 계약과 충돌했다.
Source 판단 앞에 생성형 need를 추가하면 중복 재해석 경계가 늘어난다. v7의
추가 호출을 넓히거나 binding Prompt만 패치하지 않는다.

다음 v8은 v4의 모달리티 안전 표현을 유지하면서 Source와 Output 역할만 함께
결정한다. v2와 달리 prohibition/status owner를 합치지 않으며, Source 음성목록 및
fact enum 반환을 강제하지 않는다. 양쪽 역할이 같은 원문 해석을 소비하는 것이
목적이다. Core 001/009/013/019/023/025/027/045/049를 compiled RU→Route에서
각 1회, 유력하면 같은 집합 1회 반복한다. reference time은 기존 v4 actual input으로
고정한다. 009는 READ→WRITE 반례다. 새 Output 오판/Source 손실이 지속되면 전수
평가를 실행하지 않는다. 062 결과와 이번 수치의 채점 범위 차이를 별도 기재한다.

v8 첫 출력에서도 009 READ→SEND/CREATE, 023 Task 누락이 남았다. 이 Source/Output
fusion은 확대하지 않는다. 마지막 좁은 표현 대조 v9는 v4 specialist owner를 유지하고
Source를 닫힌 **optional Resource-key map**으로 출력한다. enum value와 opaque ref의
결속을 별도 생성하지 않으며, 배열 exact-set/중복 ID 계약도 필요하지 않다. 모든 Resource를
선택할 자유는 유지한다. Source 자체를 결정적으로 선택하지 않는다. 동일 frozen Core8에
각 1회, 기존 성공 누락이 남으면 반복·92 실행 없이 기각한다. 이는 003 sparse array와
다른 key-owned binding 표현의 비교이며 정보 요구를 새로 중간 재해석하지 않는다.

v9도 013을 Draft Source로 바꾸고 023/025의 필수 Source를 누락해 기각한다.
추가 Source 규칙 대신 실제 provider envelope를 점검했다. 현재 `/api/generate`는
출력 Schema를 `format`뿐 아니라 사용자 prompt 본문에 다시 넣는다. v10은 Source
판단의 중복 schema 본문만 제거한다. 기존 Prompt/Schema/input/validator/모델/샘플링은
같고 constrained decoding은 유지한다. 원문이나 의미 필드를 삭제하지 않는다.
같은 Core8 frozen Source 입력 각 1회(최대 repair 1회)로 끝내고, 유의미한 개선이
없으면 더 많은 형식 patch와 전수 실행을 중단해 최선의 v4 및 재현 근거를 보존한다.

## 최종 결과 — Production 유지, 신규 후보 모두 REJECT

062 v4보다 안정적이라는 근거를 확보하지 못했다. Source 선택과 금지 보존의 잔여
실패를 해결했다고 보고하지 않는다. 5개 후보의 고정 진단을 수행했으며, 실패를
교체하는 반복과 신규 Canonical 92 실행은 하지 않았다. Product code/Prompt/manifest,
Node/State/Approval/Execution/Verification/Recovery 변경은 **0**이다.

### 실제 connected Core 9 재검토

| 비교 | PASS | PARTIAL | FAIL | 실제 연결 Route |
| --- | ---: | ---: | ---: | ---: |
| Production 기존 raw | 3 | 1 | 5 | 8/9 |
| v4 기존 raw | 3 | 2 | 4 | 8/9 |
| v8 신규 compiled RU→Route | 3 | 1 | 5 | 8/9 |

이는 새 92개 점수가 아니며, 단순 Resource/effect 쌍 일치도 아니다. 수동 판정과 근거는
`063-semantic-review.json`에 Case별로 보존했다. Core-019는 소요시간을 발명하지 않고
관련 READ로 가는 prefix를 허용한다. 후속 사용자 확인 완료는 미검증이다.
현재 Production의 역사적 92 기록 `32/3/57`, 062 v4의 역사적 `53/1/38`은 보존하되,
이번 작은 집합의 수정 판정을 전체 92에 외삽하지 않는다. 062의 전체 총점은 재검토 필요다.

| Case | 최초 문제/변화와 판정 |
| --- | --- |
| 001 | selected Thread identity와 READ 목적 유지. v8의 Source Message 후보는 실제 Thread route에 결속. PASS |
| 009 | Goal/Output에서 '메일·작업을 근거로 상태 답변'을 '메일로 전달·Task 생성'으로 바꿈. SEND/CREATE가 붙어 FAIL |
| 013 | v4는 Source 없음. v8은 Route에서 Task/Event 보강되지만 completion에 발송을 추가. Draft-only 의미 FAIL |
| 019 | v4/v8 모두 선호 시간과 두 작성안을 보존하고 READ 진입. RU 직후 확인 미발생만으로 FAIL 처리하지 않음 |
| 023 | v4 성공에서 v8 Task Source/Route 누락으로 회귀 |
| 025 | Production 성공에서 v8 전 Source 선택→불필요 확인으로 회귀. raw `NO_ROUTE`는 phase상 WAITING_CONFIRMATION이며 예외가 아님 |
| 027 | 관련 조회는 유지되지만 CREATE 금지가 typed prohibition에서 누락. PARTIAL, business PASS 아님 |
| 045 | v4 all-not-required 계약 실패에서 v8 메일/Task/Calendar 및 ANSWER route 복구 |
| 049 | 세 Output pair는 맞지만 메일 Source가 Draft로 바뀌고 completion이 생성/완료를 혼합. FAIL |

Production PASS 회귀 1건(025), v4 PASS 회귀 1건(023)이다. 045 하나의 복구가
이 회귀를 상쇄하지 않으므로 채택하지 않는다. 실제 불필요 WRITE **제안**은 v8 009의
SEND+Task CREATE 1 Case/2 routes이며, 013은 route가 아닌 completion 오염이다.
실제 Provider WRITE/SEND는 0이다. 다른 scope의 062 `22→2`와 합산하지 않는다.

### Source-only 후보

| 후보 | 새 실제 호출 | Product Source schema valid | 중단 근거 |
| --- | ---: | ---: | --- |
| v6 demand-first/ref | 8 | 7/8 | ref 중복, Task 누락, Source/새 Output 혼동 |
| v7 needs→binding | 16 | 5/8 | 생성된 need에서 원문 의미 변경; null/scope merge 계약 실패 |
| v9 optional key map | 8 | 8/8 | 문법은 안정돼도 Task/메일 누락, Draft/GitHub 오선택 지속 |
| v10 schema format-only | 8 | 8/8 | 023/027/045 Source 회수 가능, 그러나 025 메일 누락·013 Source 한정 위반·049 Draft 대체 |

Source-only 8건을 connected 9건 또는 최종 업무 성공 분모로 섞지 않는다.
최초 runner는 반환만 `SOURCE_RETURNED`로 표시했다. raw를 고치지 않고 후속
schema 확인으로 모든 반환 결과를 재검증했다. v7의 3건은 null binding/scope merge
오류로 반환되지 않았고 나머지 5건은 schema valid다. runner는 이제
**반환/Schema 통과/의미 통과**를 분리한다.

### 관측·재현 개선

- 실패 전 owner input을 먼저 기록하고 예외를 남긴다.
- 실제 Ollama transport에서 첫 출력·repair·실패 호출을 계수한다. timeout usage가 없으면
  missing count로 표시하며 0-token 성공으로 처리하지 않는다.
- 실제 input/schema/instruction hash, temperature/seed/model/timeout을 기록한다.
- 이전 actual reference time을 읽어 고정하는 옵션과 실제 budget reference timestamp 추가.
- Source replay는 기존 owner 입력을 그대로 재사용한다. Dataset/Gold는 모델에 전달하지 않는다.
- `NO_ROUTE`로 뭉개졌던 WAITING_CONFIRMATION 관측을 phase 기준으로 구분한다.

v8의 Core9 actual reference time은 v4와 모두 같다. Production raw와 v4는 001/009/013에서
시각이 달랐고 023은 Goal 이전 실패로 비교할 reference가 없다. 따라서 Production과의
엄격 paired runtime 효과나 반복 안정성 향상을 주장하지 않는다. temp 0/seed 고정의
단발 결과를 반복 신뢰성으로 표현하지 않는다.

| 범위 | calls | input tokens | output tokens | reported latency ms |
| --- | ---: | ---: | ---: | ---: |
| Production Core9 기존 recorder | 60 | 154,001 | 5,771 | 366,179 |
| v4 Core9 기존 recorder | 56 | 142,686 | 7,818 | 343,779 |
| v8 Core9 transport 실측 | 48 | 111,099 | 8,419 | 350,647 |
| 신규 진단 전체(서로 다른 scope 합계) | 88 | 178,281 | 15,289 | 636,796 |

기존 recorder 값은 실패/내부 repair의 실제 호출 수를 완전히 보장하지 않는다. 호출 감소로
제품 성능 개선을 선언하지 않는다. v8은 기록상 입력이 줄어도 출력·지연은 늘었다.

### 남은 구조 문제와 ownership

| 의미 | producer → 검증 → State/projection → consumer/revision |
| --- | --- |
| 업무 경계/원문 | 기존 WorkUnit owner → exact provenance → item work_unit_ids → 각 RU owner |
| Goal/Output | v4 또는 v8 공동 owner → schema/WorkUnit IDs → immutable cached projection → merge; 의미 수정은 producer 책임 |
| Source | specialist(v4/v6/v9/v10), needs+binding(v7), 공동 owner(v8) → ref/schema → Product Source decision → merge/Route |
| 금지 | 기존 prohibition owner → closed effect/binding → RequestIntent → 기존 Policy; 후보가 값 보정하지 않음 |

원문이 입력에 있어도 생성된 completion/need가 의미를 바꾸며, Resource field metadata와
필요한 업무 사실의 결속이 불안정하다. 원문 저장만으로 해결되지 않았고 Source/Output을
무조건 합치거나 분리하는 것도 답이 아니었다. 현재 근거로 '모델 한계'라고 확정하지 않는다.
새 Source 업무 artifact의 표현력/후속 소비를 바꾸려면 #288의 ownership·migration 검토가
필요하다. 이번 기각 후보의 Prompt patch나 budget 증가로 Production을 밀어 넣지 않는다.

### 검증과 보존

- 직접 후보/관측 + 기존 Source/merge/prohibition tests **62 passed**.
- 변경 Python 4개 ruff, scoped mypy(`--follow-imports=skip`) PASS. 전체 pytest 미실행.
- raw만으로 최초 의미 변경이 확인돼 LangSmith 추적용 추가 Run을 만들지 않았다.
- Retrieval/Planning/승인 후 실행, 92 전수 재평가, 반복 안정성은 미검증이다.
- 비활성 후보·테스트·사전 계획·판정은 Git에 보존한다. 상세 원문/raw는 ignored
  `evaluation/results/063-*/raw.json`, 집계는 `evaluation/results/063-summary-v3.json`이다.
- 재집계: `python -m scripts.summarize_ru_stabilization --output evaluation/results/063-summary-new.json`.
  기존 결과 경로가 있으면 덮어쓰지 않는다. 사용한 raw hash는 집계 파일에 있다.
