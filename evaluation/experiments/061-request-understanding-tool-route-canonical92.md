# 061 — Canonical 92 Request Understanding → Tool Route 전수 측정

Issues: #287 / #288

## 결론

고정된 Production SHA에서 Canonical v8 92개를 각각 한 번 실행하고, 사용자 원문과
Canonical 의미를 final `RequestIntentV3` 및 Tool Route에 직접 대조했다.

| 범위 | PASS | PARTIAL | FAIL | 엄격 성공률 | PASS+PARTIAL |
| --- | ---: | ---: | ---: | ---: | ---: |
| CORE 60 | 17 | 2 | 41 | 28.3% | 31.7% |
| HOLDOUT 12 | 6 | 1 | 5 | 50.0% | 58.3% |
| STRESS 20 | 9 | 0 | 11 | 45.0% | 45.0% |
| **전체 92** | **32** | **3** | **57** | **34.8%** | **38.0%** |

Graph 예외 없이 해당 경계를 마친 Case는 `72/92(78.3%)`, 실제 Route artifact까지
생성한 Case는 `69/92(75.0%)`였다. 따라서 구조 도달률을 업무 의미 성공률로 해석할 수
없다. 중복 사용자 원문을 하나로 센 87개 기준 엄격 성공률도 `31/87(35.6%)`로 거의
같다.

이번 결과는 RU → Tool Route 경계의 성공률이다. Retrieval, Planning, 실제 Provider,
STRESS fault 주입 결과나 Canonical 92 E2E 성공률이 아니다.

## 실행 결속

- Product SHA: `50ff0879c1cbdbdde0fd0b6969c664e9670b2404`
- Dataset: Canonical v8 `CORE 60 / HOLDOUT 12 / STRESS 20`
- Model: `qwen3.5:9b`
- Model digest: `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`
- Temperature / seed / 반복: `0.0 / 20260923 / Case당 1회`
- Product LLM: `607 calls / 1,545,043 input tokens / 58,313 output tokens`
- 보고 latency 합계: `3,357,449ms`
- Provider READ / WRITE / SEND: `0 / 0 / 0`
- 로컬 raw: `evaluation/results/ru-tool-route-canonical92-20260924-50ff0879/raw.json`

Holdout과 Stress는 frozen SHA의 최종 측정에만 포함했고 후보 튜닝에 사용하지 않았다.
Stress는 fault를 실제 주입하지 않았으므로 fault recovery 성공 여부가 아니라, fault 이전
RU/Route 의미만 판정했다.

## 판정 기준

- `PASS`: 독립 업무, Source 범위, Output/effect, 대상·시간·수량·금지 및 필요한 확인이
  materially 보존됨
- `PARTIAL`: 실제 Route는 안전하고 핵심 업무는 유지됐으나, 명시적 비실행 금지가 typed
  prohibition으로 끝까지 결속되지 않음
- `FAIL`: 필수 Source/업무 누락, 불필요 Source 확장, 요청하지 않은 WRITE, effect/시간 변경,
  잘못된 확인 또는 구조 오류

특정 Tool 순서나 유일한 decomposition 모양은 요구하지 않았다. Canonical의 최종 사실,
fault, 승인 후 효과처럼 이 경계에서 아직 알 수 없는 내용도 채점하지 않았다.

추가 ambiguity 감사에서는 다음 원칙을 적용했다.

- 원문에 둘 이상의 자연스러운 업무 해석이 있으면 특정 Gold 모양과 다르다는 이유만으로
  실패시키지 않는다. 필요한 의미와 금지를 보존한 합리적 해석이면 허용한다.
- 하나의 WorkUnit과 여러 WorkUnit이 모두 의미를 보존할 수 있으면 exact 개수를 채점하지
  않는다. 명시적 산출물 의존이나 서로 다른 제약의 귀속이 실제로 사라진 경우만 실패다.
- 필요한 Source가 보존된 상태의 넓은 READ 후보는 의미 실패가 아니라 효율 문제로
  분리한다. 사용자가 Source를 제한했거나 금지한 경우는 예외다.
- 요청·접근 데이터만으로 판정할 수 없는 Dataset Case는 분모에서 숨겨 실패로 만들지
  않고 별도 `SKIP_DATASET_AMBIGUITY`로 기록한다.

이 기준으로 CORE-015/045/047/058과 HOLDOUT-006을 FAIL에서 PASS로 재분류했다.
현재 92개에서는 분모에서 제외해야 할 Dataset ambiguity는 확인되지 않았다. 이는 하나의
해석을 강제했다는 뜻이 아니라, 위 5건처럼 복수의 유효한 표현을 PASS로 허용한 뒤에도
남은 실패가 required/forbidden 의미 또는 구조 계약으로 판별 가능했다는 뜻이다.

로컬 9B 모델을 이용한 자동 semantic judge도 시도했지만 폐기했다. 후보 Source 목록을
실제 선택으로 오독한 뒤 보정을 거쳐도 CORE-009의 READ→SEND/CREATE와 CORE-012의
Draft→SEND를 PASS로 판정했다. 이 결과는 분모나 점수에 사용하지 않았고, 관련 judge
코드도 채택하지 않았다.

## 실패 규모

구조 오류 20건의 직접 원인은 다음과 같다.

- exact request span 결속 실패: 8건
- Source/status/goal revision·provenance 계약 실패: 8건
- Output schema 계약 실패: 3건
- LLM timeout: 1건

구조를 마친 72건에서도 `PASS 32 / PARTIAL 3 / FAIL 37`이었다. 의미 실패는 서로 겹칠 수
있으며, 수평적으로 반복된 패턴은 다음과 같다.

- 필수 Source 누락 또는 금지된 Source 확장: 22건
- 요청하지 않은 Output 추가 또는 effect 변경: 22건
- WorkUnit 경계·relation 손실: 8건
- 시간·수량·상태 조건 변형: 6건
- safe Route였지만 명시적 비실행 금지의 typed 결속 누락: 3건

즉 한 업무 명사에 대한 규칙 누락이 아니다. 같은 원문 의미를 atomic owner들이 다시
생성하면서 Source/Output/Goal이 서로 독립적으로 확장·축소하고, validator는 schema와
Registry 적합성만 확인해 그 의미 변형을 막지 못하는 전체 ownership 문제다.

## Case별 판정과 최초 차이

### CORE

| Case | 판정 | 최초 차이 | 실제 차이 |
| --- | --- | --- | --- |
| CORE-001 | PASS | 없음 | 선택 Gmail Thread 단일 READ, WRITE 없음 |
| CORE-002 | PASS | 없음 | 선택 Gmail 근거만 조회, Task/Calendar 없음 |
| CORE-003 | PASS | 없음 | 선택 자료 범위와 답변 업무 보존 |
| CORE-004 | FAIL | Output schema | structured output 계약 위반 |
| CORE-005 | PASS | 없음 | 상태·기한 조회와 새 작업 금지 보존 |
| CORE-006 | PASS | 없음 | 요청 Source와 read-only 의미 보존 |
| CORE-007 | PASS | 없음 | 요청 Source와 read-only 의미 보존 |
| CORE-008 | PASS | 없음 | 요청 Source와 read-only 의미 보존 |
| CORE-009 | FAIL | Output owner | 현황 READ에 Gmail SEND와 Task CREATE 추가 |
| CORE-010 | PASS | 없음 | 요청 Source와 read-only 의미 보존 |
| CORE-011 | FAIL | Output owner | Draft CREATE에 SEND 추가 |
| CORE-012 | FAIL | Output owner | Draft CREATE에 SEND 추가 |
| CORE-013 | FAIL | Output owner | Draft CREATE에 SEND 추가 |
| CORE-014 | FAIL | Source owner | Task Source 누락, Draft 외 Task/Event WRITE 추가 |
| CORE-015 | PASS | 없음 | Task+Calendar 근거와 Draft Output 보존; 추가 Gmail READ는 효율 문제 |
| CORE-016 | FAIL | Source owner | 광범위 Source와 SEND를 추가하고 불필요 확인으로 종료 |
| CORE-017 | FAIL | span binding | exact request span 계약 실패 |
| CORE-018 | FAIL | Source owner | 필요한 Source 0건, Draft에 SEND 추가 |
| CORE-019 | FAIL | Source owner | Fjord Gmail Source 누락; 관련 READ 후 확인 허용은 유지 |
| CORE-020 | FAIL | Source owner | Draft 작성에 기존 Gmail Source와 SEND 추가 |
| CORE-021 | FAIL | Output owner | Event CREATE에 Gmail Draft CREATE 추가 |
| CORE-022 | PASS | 없음 | Gmail/Task/Freebusy 근거와 Event 결과 보존 |
| CORE-023 | FAIL | span binding | exact request span 계약 실패 |
| CORE-024 | FAIL | Goal/constraint | 11:00 시작을 11:30 시작으로 변경 |
| CORE-025 | PASS | 없음 | 요청 Source와 결과 의미 보존 |
| CORE-026 | FAIL | Source owner | Gmail/Task Source 누락, Event에 SEND 추가 |
| CORE-027 | PARTIAL | prohibition owner | read-only Route지만 `일정 만들지 마` typed 금지 누락 |
| CORE-028 | FAIL | Source owner | 불필요 Gmail 하위 Source와 SEND 추가 |
| CORE-029 | FAIL | Output owner | 요청하지 않은 Gmail Draft CREATE 추가 |
| CORE-030 | FAIL | Goal/constraint | 13~14시를 14~15시로 변경하고 세 WRITE 추가 |
| CORE-031 | FAIL | Source owner | 기존 근거 Source 누락, Task 외 Event CREATE 추가 |
| CORE-032 | FAIL | Source owner | 기존 Task Source 누락, Event CREATE 추가 |
| CORE-033 | FAIL | span binding | exact request span 계약 실패 |
| CORE-034 | FAIL | span binding | exact request span 계약 실패 |
| CORE-035 | FAIL | Output owner | Task CREATE에 Event CREATE 추가 |
| CORE-036 | FAIL | Source owner | Task Source 누락, Draft/Event WRITE 추가 및 날짜 변형 |
| CORE-037 | FAIL | Source contract | same-resource Source invariant에서 차단 |
| CORE-038 | FAIL | span binding | exact request span 계약 실패 |
| CORE-039 | FAIL | status provenance | Source status provenance 계약에서 차단 |
| CORE-040 | FAIL | span binding | exact request span 계약 실패 |
| CORE-041 | FAIL | Source contract | 필요한 Source가 모두 비어 계약에서 차단 |
| CORE-042 | FAIL | Source owner | Task Source 누락 |
| CORE-043 | FAIL | Source owner | Task Source 누락 |
| CORE-044 | FAIL | Source contract | 필요한 Source가 모두 비어 계약에서 차단 |
| CORE-045 | PASS | 없음 | 세 필수 Source와 read-only 결과 보존; 넓은 Gmail READ는 효율 문제 |
| CORE-046 | FAIL | WorkUnit owner | 두 결과를 한 업무로 합치고 Gmail/Task Source 누락 |
| CORE-047 | PASS | 없음 | Task UPDATE와 Event CREATE 및 각각의 시간 보존; 의존이 없어 한 WorkUnit도 허용 |
| CORE-048 | FAIL | span binding | exact request span 계약 실패 |
| CORE-049 | FAIL | WorkUnit owner | 세 결과를 한 업무로 합치고 Gmail/Task Source 누락 |
| CORE-050 | FAIL | WorkUnit owner | 세 결과를 한 업무로 합치고 Source 일부 누락 |
| CORE-051 | FAIL | Output owner | 답변 요청을 Draft/Task/Event WRITE로 변경 |
| CORE-052 | FAIL | runtime | LLM timeout |
| CORE-053 | FAIL | Output owner | Event 요청에 Draft CREATE 추가, 필요한 확인 누락 |
| CORE-054 | PASS | 없음 | Grove 근거와 reply Draft 결과 보존 |
| CORE-055 | PASS | 없음 | 요청 Source와 결과 의미 보존 |
| CORE-056 | PARTIAL | prohibition owner | 안전한 read-only Route지만 `실행하지 마` typed 금지 누락 |
| CORE-057 | FAIL | Source owner | Source 누락, Task 외 Event WRITE와 불필요 확인 추가 |
| CORE-058 | PASS | 없음 | Event 시각·Output과 충돌 READ 보존; 추가 READ 후보는 효율 문제 |
| CORE-059 | PASS | 없음 | Gmail 근거와 SEND 결과 보존 |
| CORE-060 | FAIL | Goal/constraint | 완료 UPDATE에 요청하지 않은 `due=now` 추가 |

### HOLDOUT

| Case | 판정 | 최초 차이 | 실제 차이 |
| --- | --- | --- | --- |
| HOLDOUT-001 | PASS | 없음 | 요청 의미와 Route 보존 |
| HOLDOUT-002 | PASS | 없음 | 요청 의미와 Route 보존 |
| HOLDOUT-003 | PASS | 없음 | 인증서 Source와 read-only 의미 보존 |
| HOLDOUT-004 | FAIL | Source owner | Source 범위 확장 후 Event CREATE 추가 |
| HOLDOUT-005 | PASS | 없음 | Calendar read-only와 권한 조건 보존 |
| HOLDOUT-006 | PASS | 없음 | Task 근거와 read-only 결과 보존; 추가 Draft READ는 효율 문제 |
| HOLDOUT-007 | FAIL | Output schema | 서로 다른 두 Draft가 duplicate Output으로 거절됨 |
| HOLDOUT-008 | PARTIAL | prohibition owner | 안전한 read-only Route지만 `변경하지 마` typed 금지 누락 |
| HOLDOUT-009 | FAIL | Output owner | Task UPDATE를 Task/Draft CREATE로 변경 |
| HOLDOUT-010 | FAIL | WorkRelation owner | Event와 후속 Draft를 한 업무로 합쳐 의존 관계 소실 |
| HOLDOUT-011 | PASS | 없음 | 요청 의미와 Route 보존 |
| HOLDOUT-012 | FAIL | Output schema | Gmail delete 요청의 안전한 거절 대신 schema 오류 |

### STRESS

| Case | 판정 | 최초 차이 | 실제 차이 |
| --- | --- | --- | --- |
| STRESS-001 | PASS | 없음 | fault 이전 요청 의미와 Route 보존 |
| STRESS-002 | FAIL | WorkUnit owner | error contingency를 별도 업무로 승격하고 Task Source 누락 |
| STRESS-003 | PASS | 없음 | fault 이전 요청 의미와 Route 보존 |
| STRESS-004 | PASS | 없음 | fault 이전 요청 의미와 Route 보존 |
| STRESS-005 | PASS | 없음 | fault 이전 요청 의미와 Route 보존 |
| STRESS-006 | PASS | 없음 | fault 이전 요청 의미와 Route 보존 |
| STRESS-007 | PASS | 없음 | fault 이전 요청 의미와 Route 보존 |
| STRESS-008 | PASS | 없음 | fault 이전 요청 의미와 Route 보존 |
| STRESS-009 | PASS | 없음 | fault 이전 요청 의미와 Route 보존 |
| STRESS-010 | PASS | 없음 | fault 이전 요청 의미와 Route 보존 |
| STRESS-011 | FAIL | Output owner | Task 요청에 Event CREATE 추가 |
| STRESS-012 | FAIL | span binding | exact request span 계약 실패 |
| STRESS-013 | FAIL | WorkUnit owner | 두 결과를 한 업무로 합치고 Gmail/Task Source 누락 |
| STRESS-014 | FAIL | Source owner | Event Source/WRITE 추가, due 13:00을 17:00으로 변경 |
| STRESS-015 | FAIL | Source/status contract | current-run binding 없는 Source status로 차단 |
| STRESS-016 | FAIL | Source/status contract | current-run binding 없는 Source status로 차단 |
| STRESS-017 | FAIL | Source/status contract | current-run binding 없는 Source status로 차단 |
| STRESS-018 | FAIL | Source/status contract | current-run binding 없는 Source status로 차단 |
| STRESS-019 | FAIL | WorkUnit owner | 세 결과를 한 업무로 합치고 Task UPDATE를 CREATE로 변경 |
| STRESS-020 | FAIL | WorkRelation owner | Event와 후속 Draft를 한 업무로 합쳐 취소 경계 소실 |

## 수정 방향

다음 변경은 `A가 틀리면 A 규칙 추가` 방식으로 진행하지 않는다.

1. Goal/Source/Output owner가 같은 사용자 의미를 독립적으로 재생성하는 현재 경계를
   하나의 semantic authority와 deterministic projection으로 재검토한다.
2. validator는 모델 대신 업무 의미를 만들지 않되, 원문에 없는 WRITE와 closed
   WorkUnit/source binding 불일치를 producer 계약 수준에서 거절할 수 있어야 한다.
3. WorkUnit, Source, Output의 item-owned binding을 실제 owner 입력과 첫 출력에서부터
   유지하고 downstream에서 원문을 다시 해석해 복원하지 않는다.
4. 성공 27건, 반례, structural 20건을 함께 고정해 전체 성공률과 실패 분포가 개선되는
   후보만 채택한다.

이번 단계는 측정만 수행했다. Product, Prompt, Schema, State, Node 변경은 없다.
