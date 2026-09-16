# 008. 현재 Evidence → Work Analysis 입력 경계

기준 SHA `ef3ea83d`, corpus `canonical92-v8-5a49aa00-ecf32ffc82`.
006의 저장 checkpoint에는 Work Analysis 적용 입력이 0건이지만, 007의
현재 RU→Route→Retrieval 합성 연결은 `021/028`에 Evidence와
`WORK_ANALYSIS` handoff를 만들었다. 이 in-memory 출력을 그대로 다음
consumer에 전달한다. 저장 corpus의 과거 RetrievalResult나 정답 Evidence를
끼워 넣지 않는다.

가설은 인접 handoff의 GraphState·EvidenceStore 계약이 Work Analysis의
초기 호출에서 소비 가능하다는 것이다. 먼저 021 한 건만 직렬 실행하고,
Schema/입력 오류라면 제품 Node 평가와 분리해 harness를 바로잡는다.
그다음 028의 다른 시간 표현을 대조한다. 목표는 WorkAnalysisResult와
next target의 형성·첫 호출 분포 확인이지 최종 업무 성공 선언이 아니다.
first-call schema valid와 semantic valid를 분리하고, 원문 대상·시각·부정·
관계가 Work Analysis 출력에 남는지 별도 확인한다. 실제 Provider READ,
WRITE, Planning·Review는 실행하지 않는다.

한 평가 프로세스씩 실행한다. 기존 014의 Planning handoff는 Work Analysis
비적용 성공 대조로 007 결과를 재사용한다. 015의 Task 미조회는 upstream
미도달로 남기고 Work Analysis 실패 분모에 넣지 않는다. 결과의 비민감
요약만 버전관리하고, raw synthetic Evidence·원문은 ignored results에 둔다.

## 첫 연결 관측

021: 현재 Producer 7회 → Retrieval LLM 3회·synthetic READ 5회 →
Work Analysis LLM 5회. Evidence 5건을 실제 in-memory EvidenceStore에서
소비해 WorkAnalysisResult를 만들고 `SOLUTION_PLANNING`으로 전달했다.
출력은 사실 6건, 관계 0건, 모호성·위험 0건, route별 action necessity 1건,
전체 action necessity `REQUIRED`였다. Work Analysis 입력/출력 token은
46,027/1,795, 66.9초였다. 이는 Schema/Graph 연결 성립이지, 8월 14일
10시·60분 및 출고 메일·두 Task의 의미 보존이 검증됐다는 판정은 아니다.
Relation 0건도 정답·오답으로 단정하지 않고 원인 검토 대상으로 남긴다.

028: 현재 Producer와 Retrieval은 정상이고 Evidence 5건·synthetic READ 6회가
Work Analysis 입력에 도달했다. 첫 Work Analysis provider dispatch에서
구조화 결과 없이 `LLMInvocationError`로 종료됐고 후단 기록 LLM 호출은 0회,
지연은 180.2초였다. 현재 local timeout 계약 `180초`와 일치하므로 시간초과가
유력하지만, 최초 기록에는 typed error code가 없어서 확정하지 않는다.
동일 데이터의 Evidence JSON 길이는 021 약 2,820자, 028 약 2,778자로
큰 입력 차이만으로 설명되지는 않는다. 실패를 모델 의미 오판이나
Work Analysis Schema 실패로 분류하지 않는다. 후속 Trial에서는 typed error code와
dispatch 발생 여부, 첫 Prompt 입력 크기·지연만 비민감하게 기록하도록 harness를
보완했다. 028 한 건을 같은 모델·seed로 한 번만 추가 재생해 실패의 반복 여부를
확인한다. 이전 실패 Trial을 삭제하거나 PASS로 대체하지 않는다.

추가 028 Trial은 같은 상위 Route·모델·seed에서 성공했다. Retrieval Evidence
4건을 소비했고, 첫 `extract_work_facts` 입력은 약 4,711자·40.4초였다.
Work Analysis는 5회 LLM 호출·48,066/2,417 input/output token·83.8초로
사실 11건, 관계 0건, route action necessity 1건을 만들고
`SOLUTION_PLANNING`으로 전달했다. 따라서 180초 실패는 같은 입력 family에서
고정 재현되지 않았다. 현재 관측은 028 **실패 1/성공 1**이며 모델·런타임
지연 변동을 분리하지 못했다. 성공 Trial만 골라 first-call 안정화라고
주장하지 않는다. 두 Trial 모두 실제 Provider·최종 업무 성공은 미검증이다.
추가 원시 결과는
`evaluation/results/request-to-work-analysis-repeat-core028-20260916/`에 있다.

첫 Trial의 denominator는 현재 연결상 Work Analysis 적용 2건이다.
021의 결과 생성 1건, 028의 첫 provider 실패 1건이며 first-call semantic-valid
판정은 0건 완료(미평가)다. 반복 Trial은 028 한 건을 별도로 세며, `WorkAnalysisResult`가 나왔다는 이유로 1/2 의미
성공이라고 세지 않는다. 실제 Provider·Planning·Review·WRITE는 미실행이다.
원시 결과는 `evaluation/results/request-to-work-analysis-core021-20260916/`와
`request-to-work-analysis-core028-20260916/`에 분리 보존했다.
