# 003. Request Understanding Source 판정 입력 분리

## 기준·원인 가설

기준 SHA는 `8055af4c40acb7f174c07af09240389b5ec51fb9`이다. 저장된 Core 60의
RequestIntent를 원문과 대조하면 Task 사실이 필요한 일부 요청에서 `TASK`가 빠지고
`TASK_LIST`만 남는다. `identify_source_dependencies`는 원문을 이미 입력받으므로
원문 부재로 단정하지 않는다. 가설은 앞 호출의 중복·오해 가능 제약을 함께 전달하는
표현과 exact-set 10-Resource 판단 부담 중 적어도 하나가 영향을 준다는 것이다.
고정 corpus는 `canonical92-v8-5a49aa00-ecf32ffc82`, 모델 digest는
`6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`다.
Goal/Source Prompt hash는 각각 `98fc61337e02e8cc7099f52925bccbbc03e1f5a8b3f821f996c30ea5d592d7aa`,
`3954c6cc6d6d1beedcdf6c59f314faac31fbf533d789221ab18e642f130a58a6`다.

우선 **입력 표현만** 비교한다. baseline은 production의
`project_extractive_source_goal`을 사용한다. 개발 후보는 같은 원문·선택 Resource·
Run reference time·Source 후보 목록·Prompt·출력 Schema를 유지하고, Source 판단에
전달하는 앞 호출의 파생 `constraints`만 빈 동일 구조로 제공한다. 이 정보는 원문에
남아 있으므로 의미 자체를 삭제하지 않는다. 후보는 제품 코드에 연결하지 않는다.
Schema·Prompt·Source 후보 수 축소는 이번 비교에서 변경하지 않는다.

## 사전 비교 범위·중단 기준

- 대표·반례·기존 성공: Core `011/014/015/021/024/028` 6건.
- 저장된 92 corpus의 동일 사용자 원문으로 production `identify_goal` 출력을 한 번
  만들고, **같은 출력**에서 baseline과 개발 후보 Source 판정을 직렬 호출한다.
- 실제 Connector·Product Graph·WRITE는 실행하지 않는다. Local `qwen3.5:9b`,
  temperature `0`, seed `1729`로 1차 paired 비교 후 유력할 때만 같은 6건을 1회
  반복한다. 빠르거나 PASS가 나올 때까지 재실행하지 않는다.
- Schema-valid와 원문 Source 의미를 분리한다. 필요한 Task·Gmail·Calendar 사실
  owner 누락과, Output Resource를 Source로 오인하거나 container를 업무 사실로
  과잉 선택하는 것을 모두 실패로 본다. 수치가 좋아도 안전·권한 변화 또는 기존
  성공 사례의 소스 손실이 있으면 채택하지 않는다.
- 성공 기준은 6건 중 의미상 유효한 Source 선택이 baseline보다 증가하고,
  누락·과잉 양쪽에서 개선되며 반복에서도 유지되는 것이다. 품질 이득 없는 호출·토큰
  증가를 허용하지 않는다.

## 기준 진단 (제품 변경 없음)

동일 `identify_goal → identify_source_dependencies`만 실행한 2회 Trial에서 각
Case의 Source type 출력은 동일했다. 양쪽 호출은 매 Case 1회씩이며 Schema는 모두
통과했다. 수동 의미 검토는 Dataset category만으로 판정하지 않고 원문과 06의
Resource 사실 Owner를 기준으로 했다.

| Case | Source 선택 | 의미 판정 |
| --- | --- | --- |
| 011 | Gmail Thread/Message/Draft, Task List/Task, Calendar/Event/FreeBusy | Task·Event 외 과잉 |
| 014 | Task, Calendar Event | 원문 Source 충족 |
| 015 | Gmail Draft, Task List/Task, Calendar/Event/FreeBusy | Draft·container 과잉 |
| 021 | Gmail Thread, Task List/Task, Calendar/FreeBusy | Task List·Calendar 과잉 |
| 024 | Gmail Thread, FreeBusy | Task 누락 |
| 028 | Gmail Thread, Task List/Task, Calendar/Event/FreeBusy | container·Event 과잉 |

따라서 Schema-valid `6/6`은 첫 호출의 의미 유효율이 아니며, 이 작은 집합의
명확한 의미 유효는 `1/6`이다. 저장 checkpoint의 RU Source와 이번 baseline 출력도
달라 과거 checkpoint만 현재 Node 성능으로 사용하지 않는다.

원시 결과: `evaluation/results/request-source-decision-boundary-core6-20260916/`,
`evaluation/results/request-source-decision-boundary-core6-repeat2-20260916/`.

## 후보 결과·판정

같은 `identify_goal` output을 baseline과 후보가 차례로 소비한 paired Trial의
결과는 다음과 같다. 두 판정 모두 같은 Source 후보 10개·Prompt·출력 Schema를
사용했다. Gold가 아니라 위 원문·Owner 기준 수동 판정이다.

| Case | baseline → 원문만 남긴 후보 | 의미 변화 |
| --- | --- | --- |
| 011 | 8 Resource 과잉 → Task List/Task/Event/FreeBusy | 과잉 감소, 여전히 container·FreeBusy 과잉 |
| 014 | Task/Event → Task/Event | 기존 성공 유지 |
| 015 | Draft·Task List·Task·Calendar·Event·FreeBusy → Task/Event/Draft | FreeBusy 누락, Draft 과잉 |
| 021 | Gmail Thread/Task List/Task/Calendar/FreeBusy → 동일 | 개선 없음 |
| 024 | Gmail Thread/FreeBusy → Calendar/Event | Gmail·Task·FreeBusy 손실로 악화 |
| 028 | Gmail Thread/Task List/Task/Calendar/Event/FreeBusy → 여기에 Gmail Message 추가 | 과잉 악화 |

baseline Source provider 호출은 6회, 후보는 8회였고 후보 2건에서 Schema repair가
필요했다. Paired 전체(공통 goal 6 + baseline Source 6 + 후보 Source 8)는 입력
66,822·출력 4,195 tokens, 관측 provider 지연 116,749ms다. 현재 기록은 후보의
per-call token/latency를 별도로 저장하지 않아 양쪽 지연 우열을 주장하지 않는다.
원시 결과: `evaluation/results/request-source-decision-request-only-paired-core6-20260916/`.

**기각.** 원문이 남아 있어도 파생 제약을 일괄 비우면 Task·FreeBusy·Gmail의 필요한
결속까지 불안정해진다. 명확한 의미 유효는 `1/6 → 1/6`이며 누락 회귀가 있으므로
추가 반복이나 제품 반영을 하지 않는다. 같은 방법의 Prompt 문구 조정은 재시도
조건이 아니다. 다음에는 공통 exact-set 10-Resource 출력 부담과 Source/Output
혼동을 별도 변수로 검토하되, 기존 Prompt·Schema 계약 변경 후보는 개발 실험과
제품 활성화를 분리한다.

## 다음 방법: Source 출력의 양성 항목만 표현 (개발 후보)

첫 방법은 입력을 줄여도 누락·과잉이 함께 악화됐다. 이번에는 같은 원문, 앞 호출
goal output, 후보 Resource 10개를 유지하고, `SOURCE_NOT_REQUIRED` 10개 exact-set
반환 대신 **필요한 Source만** 반환하는 표현을 시험한다. 이에 맞춘 개발 전용 짧은
Prompt와 Schema는 하나의 출력 표현 변경으로 묶는다. 후보 source는
`evaluation/prompt_candidates/request-source-sparse-v1/`에 두며 Product manifest,
Prompt input contract, `RequestIntent`, merge caller는 바꾸지 않는다. 이 시험은
제품 Node가 아니라 Local provider 첫 호출 비교이고 production repair도 없다.
Schema·caller 변경 및 Canonical 06/15 활성화 여부는 결과가 유망한 뒤 별도 판단한다.

같은 6건을 현재 goal output에서 baseline Source 호출 뒤 후보를 **직렬** 호출한다.
성공 기준은 필요한 Source 누락 0, 불필요 Source 감소, 기존 성공 `014` 유지,
Schema 첫 호출 유효와 호출·토큰 부담을 함께 보는 것이다. 6건 중 한 건의
점수만 개선하거나 새로운 의미 손실이 생기면 중단한다. 유망할 때만 동일 조건
2차 반복과 더 넓은 반례로 확장한다.

### 관측과 판정

후보는 첫 provider 호출 6/6에서 개발 Schema를 통과했고, 합계 입력 12,271·출력
398 tokens, provider 지연 14,033ms였다. 짧은 출력으로 토큰·지연은 감소했지만
같은 goal output에서 필요한 사실 owner가 다음처럼 바뀌었다.

| Case | 양성 항목 후보 | 원문 기준 결과 |
| --- | --- | --- |
| 011 | Task List, Calendar Event | Task 상태 owner 누락 |
| 014 | Task, Calendar Event | 유지 |
| 015 | Calendar Event, FreeBusy | Task 상태 owner 누락 |
| 021 | Gmail Message, Task List, Calendar Event | Thread·Task·가용성 owner 손실 |
| 024 | Gmail Message, Task List | Task·가용성 owner 손실 |
| 028 | Gmail Message, Task List, FreeBusy | Thread·Task owner 손실 |

**기각.** 의미 유효는 baseline `1/6`에서 늘지 않았고, 복수 Source 요청의 핵심
item 사실이 반복 누락됐다. 후보는 비활성 평가 파일로만 남긴다. 결과 위치는
`evaluation/results/request-source-decision-sparse-paired-core6-20260916/`다.
두 방법 모두 같은 Task item/Task List와 Gmail Thread/Message 경계에서 흔들렸다.
다음 Prompt 문구나 필드 제거를 반복하지 않는다. Source 후보의 `owned_fact_kinds`
표현, item/container 분리 책임, 후속 merge 보정의 실제 효과를 원문→후보→조립→
Tool Route 입력에서 다시 진단해야 한다. 이 후보는 품질 중단 기준에 걸려 반복 Trial
및 제품 활성화를 수행하지 않았다.
