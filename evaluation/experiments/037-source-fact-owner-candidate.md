# 037. 필요한 사실과 Source owner의 결속 표현

기준 SHA `1d909edd`. 036에서 034 저장 입력의 Task item 필요 정보가
`TASK_LIST` business Source에 결속됐지만, Source만 교정한 합성 입력에서는
**기존** Query도 Task 내용 Evidence를 확보했다. 현재 Core-023 RU 단일
Trial은 `TASK`를 선택했다. 따라서 과거 오류의 상시 재현이나 제품 개선을
가정하지 않는다. 015의 현재 RU/Route에 Task가 있어도 Query에서 누락된
별개 실패는 계속 추적한다.

003의 원문만 남기기와 Resource 양성 목록만 내는 sparse 후보는 필요한
item fact가 여러 요청에서 빠져 기각됐다. 이번 개발 후보는 단순 목록
축소가 아니라 각 Source가 **어떤 owned fact kind를 제공하는지**를 같은
출력 항목에 결속한다. 등록된 READ Resource와 기존 `owned_fact_kinds`만
사용한다. `required_information` 자유문과 target scope도 보존한다.
제품 RequestIntent·Tool Route·Prompt manifest는 아직 바꾸지 않는다.

동일 goal 첫 출력에서 현행 exact-set Source 판정과 개발 fact-bound 판정을
순서대로 한 번씩 호출한다. 고정 집합 Core `011/014/015/021/023/028`은
Task item·TaskList container·Gmail·Calendar와 기존 성공 014를 포함한다.
모델 9B digest `6488c96f…`, temperature 0, seed 1729. 최대 goal 6 +
baseline Source 6 + candidate Source 6 = 18 provider dispatch, 각 Case
Trial 1회. 후보는 별도 Prompt/Schema의 불가분한 출력 표현 변경이며,
제품 LLM 입력에는 Gold·평가 기준을 주지 않는다. 호출 실패도 결과에
남기고 성공한 재실행으로 대체하지 않는다. Connector/WRITE 0.

판정은 Schema-valid와 의미 유효를 분리한다. 필요한 item fact Source
누락 0, 014 기존 성공 유지, 불필요 container/Source 과잉 감소가 먼저다.
특정 023 하나만 개선하거나 015/021/028의 Task·FreeBusy·Gmail Source
손실이 반복되면 제품 채택하지 않는다. 후보 유력 시 동일 frozen input
1회 반복과 Query→합성 READ 연결을 검토한다. raw completion과 원문은
ignored `evaluation/results/`에만 남기며 평가 기록에는 비민감 결론만
적는다. 첫 결과로 계약을 바꾸지 않는다.

## 첫 paired 비교와 판정

사전 6개 모두 Goal 1 + 현행 Source 1 + fact-bound 후보 1 = 총 18회
직렬 호출했다. 후보 첫 출력 6/6은 개발 Schema를 통과했다. 하지만
Schema-valid를 의미 성공으로 계산할 수 없다.

| Case | 현행 Source | fact-bound 후보 | 원문·Owner 기준 |
| --- | --- | --- | --- |
| 011 | Gmail 3, TaskList/Task, Calendar/Event/FreeBusy | Task, FreeBusy | 과잉은 줄었지만 Event 필요 사실 누락 |
| 014 | Task, Event | Calendar, Event | 기존 성공의 Task 누락·container 과잉 |
| 015 | Draft, TaskList/Task, Calendar/Event/FreeBusy | Event, FreeBusy | 필수 Task 누락 |
| 021 | Thread, TaskList/Task, Calendar/FreeBusy | Message, TaskList, Event | Thread·Task·FreeBusy 손실 |
| 023 | Thread, TaskList/Task, Calendar/Event/FreeBusy | Thread, Task | Task owner 결속 개선 가능성, 단일 요청 |
| 028 | Thread, TaskList/Task, Calendar/Event/FreeBusy | Draft, Task, FreeBusy | Thread 손실·Draft Source 과잉 |

후보는 `TASK`를 선택한 경우에도 `task_identity/title/notes/due/
completion_status/task_list_identity` 전체를 한꺼번에 반환했다. 사실
kind의 필드 존재와 필요한 사실의 정확한 선택은 다르다. 014·015·021·
028에서 필요한 owner 손실이 있어 사전 중단 기준에 걸렸다. **제품 채택
기각**, 반복 Trial·Query/READ 연결은 수행하지 않는다. 후보 Prompt/Schema는
비활성 비교물로만 남기고 RequestIntent·Tool Route·manifest는 유지한다.

공통 Goal+현행 Source 12호출은 관측 36,913/2,452 tokens, provider 지연
72.9초다. 후보 6호출은 21,475/592 tokens, 27.4초다. 후보는 직접
Ollama 개발 호출이고 현행은 production runtime 경유이므로 지연 차이를
제품 비용 절감이라고 주장하지 않는다. 실패 Trial도 원시 결과에 남겼다.
고정 Goal/현행 Source Prompt hash는 `98fc6133…`/`3954c6cc…`, 후보
Prompt/Schema hash는 `3cca516e…`/`ac9d4f4f…`다. Case별 동일 Goal
출력 hash와 첫 후보 출력·호출 비용은 결과 파일에 보존했다.
원시 결과: ignored
`evaluation/results/source-fact-bound-core6-20260917/result.json`.

003의 단순 sparse 출력과 달리 fact kind 결속을 추가했지만 동일하게
복수 Source 요청에서 item 사실이 빠졌다. 또 다른 Prompt 문구나 필드
추가로 이 구조를 반복하지 않는다. 다음 원인 범위는 Source 판단의 출력
부담과 Goal 사실 분해의 책임을 함께 검토해야 한다. 특정 Resource를
키워드로 강제하거나 validator가 Source를 발명하는 방법은 제외한다.
