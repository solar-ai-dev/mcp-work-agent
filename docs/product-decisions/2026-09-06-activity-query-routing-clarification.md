# Activity·Query 전략·상태 기반 이동 — 추가 합의와 잔여 검증

수정일: 2026-09-06  
상태: 요구사항 명확화 / 구현·실제품 검증 미종결  
목적: 이후 합의의 이유와 확인 범위를 인계한다. 기능·정책·기술 계약을 대신하는 새 authority가 아니다.

## 1. 기준과 변경 범위

이번 확인의 Product 기준은 `f13dfbe81d84d2c9cbd1e0253125eb596d2ea512`다. 이전 문서 보정은 `75dc76bce706ea4559e8ef7d8c202d8eabc238ee` 및 PR 186으로 반영됐으며, 이번에도 `docs/audit-correction-notion-restructure`를 재사용한다. 과거 문서 정리·통합 기록은 당시의 인계 자료로 보존하며 실시간 완료표로 사용하지 않는다.

게시 전 Product는 `ac7c5a838d6c5682becedf0d8e14c90cb263d853`까지 전진했다. `f13dfbe8` 이후 4개 커밋의 변경 경로를 비교했으며 이번 편집 대상 PRD·기능 정의·UI/UX·문서 인덱스와 겹치지 않는다. 후속 변경의 답변 생성·정규화·Retrieval 종료 보강, 해당 테스트와 기술 계약, AGENTS 지침은 최신 Product 기반으로 보존한다. 아래 코드 관찰은 확인 당시 범위이며 후속 commit 존재만으로 제품 E2E나 3·3.1 전체 완료를 인정하지 않는다.

기능의 관찰 결과는 기능 정의, 제품 목표는 PRD, 화면·상호작용은 UI·UX에 반영한다. 기존 정책의 허용·금지·승인·최소 노출 의미는 변경하지 않는다. 기술 Canonical, Repository Architecture, SQL, API/State schema와 제품 코드는 이번 문서 작업에서 수정하지 않는다. 이 문서에 요구를 적었다고 기존 보호 계약의 예외나 구현 완료가 승인된 것은 아니다.

## 2. 7.5의 의미를 다시 명확히 한 이유

사용자가 원하는 것은 `Agent 이름 + 최종 결과의 필드/수량`만 있는 상세창이 아니다. **Agent 실행을 상위 행으로 두고, 실행 중 실제로 확인·찾기·생성·검증·복구한 작업 사실을 하위 문장으로 누적**하는 것이다.

`어떤 요청으로 이해했는지`, `무슨 기능을 선택했는지`, `어떤 사람·업무·기간을 찾는지`, `어떤 근거를 확인했는지`, `어떤 출력의 어떤 검사를 통과했는지`가 보여야 한다. 예제 문장·사람·날짜를 항상 출력하는 것이 아니라 기존 typed 결과의 실제 의미를 표시한다. 모든 내부 State 변경이나 함수 호출을 이력으로 노출하는 요구도 아니다.

부모의 진행/대기/완료 상태 갱신과 하위 사실 누적은 다르다. 종료 이벤트가 하위 기록을 덮어쓰면 안 되고, 새 Agent·새 Run이 시작돼도 이전 내역은 기존 보존 기간 안에서 남아야 한다. 같은 Conversation에서는 `요청 A → A의 Activity → 답변 A → 요청 B → B의 Activity → 답변 B`가 유지된다. 과거 Activity 보존은 새 Run의 숨은 Prompt 기억이나 이전 승인 재사용을 허용하지 않는다.

출력 형식 검증, 업무 내용과 Evidence 대조, 실제 Provider 결과 재조회는 다른 사실이다. 명시적 검사 결과 또는 보장된 성공 경계 없이 단순 값 존재를 ‘검증 완료’로 표현하지 않는다. checkpoint 복원과 실제 외부 효과 복구도 구분한다.

추가 LLM·Summary Prompt·요약 Agent·표시용 외부 Connector 조회는 없다. 현재 생성된 결과와 저장 이력을 결정적으로 표현한다. 기본 상세에서 revision·카운터·반복 disclaimer를 제거하되 정상 0건·미확인·실패는 숨기지 않는다. 실제 대체된 결과에만 `수정 전 계획` 같은 표시를 사용한다.

## 3. 현재 코드에서 확인한 7.5 간극

| 확인 경로 | 코드 관찰 | 판정 범위 |
| --- | --- | --- |
| `adapters/langgraph/activity_callback.py` | 등록된 책임 실행의 START/END/WAIT/ERROR를 관측하고 내부 작업 결과를 별도 하위 사실로 연결하지 않음 | 중간 사실 관측 연결 필요 |
| `application/use_cases/trace_event/record_run_activity.py` | 주로 END에서 goal·revision·카운터·일부 최종 필드를 추출. Tool Route 상세의 전용 의미 추출이 없음 | 문구 변경만으로 요구 충족 불가 |
| `application/use_cases/run/project_run_activity.py` | 같은 실행의 details를 이벤트 값으로 교체하고 종료된 행의 후속 관측을 무시 | 단순 이벤트 추가만으로 누적 보존을 보장하지 못함 |
| `frontend/src/features/conversation/ConversationView.tsx` | 현재 runSnapshot의 요청에 Activity를 연결 | 기록 삭제 여부와 별개로 여러 Run 동시 표시 연결 필요 |
| `frontend/src/features/run/run_progress.tsx` | 모든 행에 현재 계획과 다를 수 있다는 고정 설명과 label/value 상세 표시 | 의미 있는 하위 작업 사실 중심으로 변경 필요 |

이는 기준 HEAD의 코드 검토 결과다. 이번 문서 작업에서 실제 앱 E2E를 수행한 것은 아니며 `928da74d`의 저장·복원 구현을 버리라는 뜻도 아니다. 기존 저장/조회/관측 owner를 재사용하고 필요한 producer·projection·Conversation consumer를 같은 구현 작업에서 연결한다. 새로운 Event Store나 Activity Domain aggregate를 먼저 만들지 않는다.

## 4. 2단계와 7단계의 구분

**2단계는 State-driven Supervisor, 7단계는 Local Runtime 준비**였다. Node 이동 요구를 7단계 완료 여부와 혼동하지 않는다.

상태 기반 이동의 목표는 typed State·검증된 결과·durable fact·남은 의무로 필요한 책임을 고르는 것이다. 모든 Edge를 삭제하거나 모든 Node가 다른 모든 Node로 무제한 이동하는 구조가 목표가 아니다. 입력 의존성·승인·검증·복구 순서는 유지한다.

현재 Main Graph에는 조건부 Edge와 노드별 허용 successor가 있고 Supervisor에는 Analysis skip, 제한된 Retrieval 재진입, durable priority, freshness 및 no-progress 관련 코드가 있다. 이 코드의 존재만으로 전체 동작 PASS는 아니다. `판단한 목적지 → physical node 변환 → 허용 successor → 실제 실행`을 대조해 적법한 이동이 고정 순서 때문에 막히는지, 반대로 안전상 금지할 이동이 통과하는지 확인해야 한다. Main의 Stage 이동과 Subgraph 내부 실행은 별도 범위다.

7.5는 이 실행을 관측하는 기능이다. 표시를 고치면서 Supervisor나 3·3.1 Query 전략을 다시 설계하지 않는다.

## 5. 3·3.1에서 우선 검증할 핵심

핵심 어려움은 자연어를 이해하거나 마지막 문장을 쓰는 것보다 **어떤 첫 Query를 선택하고 반환 결과에 따라 무엇을 다음에 검색할 것인가**다. 구조·schema·Tool 연결이 정상이라는 사실과 새로운 업무 표현에서 실제 근거에 도달한다는 사실을 구분한다.

검색은 사용자 제약과 planner 가설을 구분하고 실제 관측·미해결 조건·남은 budget으로 후속 검색을 결정한다. 인물·시간·업무 개념의 복합 조건, 명시 anchor 보존, 행사일과 수신일의 차이, 적법한 페이지/detail, 후보 해소·Confirmation·같은 Run 재개를 검증한다. 동일 Query 문자열이나 정해진 Tool 순서 하나만 정답으로 강제하지 않는다.

확인 당시 `f13dfbe8` 커밋 메시지는 anchor 보존·가설 관측을 보강했지만 일반 개념 발견과 답변 사실성의 실패가 남아 Query Planning closure가 미완료라고 명시한다. 이는 해당 commit의 보고이며 이번 문서 작업이 새 측정 결과를 증명한 것은 아니다. 3·3.1은 별도 전달한 작업으로 계속하며 완료를 대신 선언하지 않는다.

### 데이터와 측정의 인계 원칙

질문마다 정답 문서만 반환하는 fixture 대신 여러 요청이 공유하는 업무 corpus를 사용한다. Source, 정상 제품 입력, Grader 전용 Gold, 실제 확인 질문 뒤 제출하는 사용자 응답 script를 분리한다. fixture는 실제 Query 인자에 따라 후보·페이지·detail을 반환하고 Gold나 Case ID로 답을 선택하지 않는다.

서로 다른 인물·시간·업무 관계의 corpus와 어려운 오답 후보, 최신 정정·취소, 연도 미확정, 정상 0건·부분 실패를 포함한다. 개발/비공개 검증/Stress를 구분하며 튜닝에 사용한 자료를 HOLDOUT으로 계속 부르지 않는다. 데이터·grader 오류와 제품 실패도 분리한다. 앞서 제안한 데이터 개수는 시작 규모이며 새로운 Canonical schema나 필수 고정 수치가 아니다.

주 측정은 정상 제품 입력으로 production Runtime/Graph와 실제 `qwen3.5:9b`를 실행하고 Query trajectory·후보 발견·Evidence·종료·비용을 확인한다. 통제된 fixture, 실제 MCP, 단독 Subgraph 진단, 브라우저 UI 검증의 증명 범위를 분리한다. 스크립트라는 이유로 검증을 무효로 보지 않고, 실제 모델·Provider를 대체했는지와 어느 경계를 통과했는지를 밝힌다. 화면 검증이 필요한 Activity 등은 실제 앱에서 확인한다.

대표 Case의 반복 실패를 best-of 성공으로 숨기지 않는다. 미검증 Query 일반화·사실성 문제를 단순 P1 안정화로 내려 완료 처리하지 않는다. 실제 검색 테스트의 외부 WRITE는 0이며 Source 개인자료·secret·Gold를 Production Prompt나 Git에 유출하지 않는다.

## 6. 앱 진입·Provider의 합의와 남은 결정

Core가 정상이면 Google/GitHub·Model Provider 미연결과 외부 전송 미동의를 이유로 메인 화면·저장 이력·Settings를 잠그지 않는다. 추론 가능한 모델이 없는 새 추론 요청은 준비 안내로 종료한다. Local-only에 외부 전송 동의를 강제하지 않으며 모델 없이 업무 의미를 해석한 것으로 처리하지 않는다. 초기 업무 Connector 부족의 요청 종료와 실행 중 Credential 만료의 기존 안전 재개는 구분한다.

앞선 코드 검토의 startup/onboarding에는 `external_llm_consent`, `llmConfigured/llmReady`를 메인 진입에 결합한 조건이 있었다. 이 결합의 제거·실제 앱 검증은 잔여 작업이며 이번 문서 변경으로 해결됐다고 표시하지 않는다.

**자동 provisioning의 최종 범위는 재확정 대기다.** 기존 7단계와 저장소의 승인 방향은 Ollama·9B 자동 준비이고, 다른 채팅에서 가져온 목록은 연결·사용 가능 여부 확인으로 축소하는 내용이다. 둘 중 하나로 임의 확정하거나 기존 구현을 삭제하지 않는다. 기존 자동 준비 요구를 이번 문서 변경으로 취소·확대하지 않으며 이 결정이 다른 잔여 작업을 막지는 않는다. 공통 기본 모델은 `qwen3.5:9b`, WORKER/REASONING 구분 유지, 4B 비필수다.

## 7. 실행 상태와 다음 검증

| 범위 | 현재 기록 | 다음 확인 |
| --- | --- | --- |
| 2 상태 기반 이동 | 관련 코드 있음 / 실제 경로 재검수 필요 | 의미 결정·물리 이동·안전상 제한 대조 |
| 3·3.1 Query 전략 | 별도 작업 진행 / f13 기준 미완료 보고·후속 보강 있음 | 실제 모델·Query-aware corpus·대표 Live MCP 측정 |
| 앱 진입·Provider | 요구 확정 / 전역 진입 조건 결합 지적 | 모두 미연결·Local-only·동의 없음에서 UI 진입 |
| 4~6.5 및 GitHub | 기존 구현·통제된 측정과 일부 Live 기록 재사용 대상 | 최신 HEAD의 실제 모델/Provider/UI 증거를 각각 확인. 과거 PARKED/PASS를 그대로 재사용하지 않음 |
| 7 Local Runtime | 자동 준비 범위 재확정 대기 | 연결·진단과 자동 설치 범위 결정 분리 |
| 7.5 Activity | 저장 기반은 있음 / 제품 의도 미충족 | 중간 작업 사실·각 검사 근거·Conversation A/B·재접속/재실행·추가 LLM/Connector 0 |
| 8 최종 통합·설치·Release | 이번 문서 작업의 완료 대상 아님 | 필수 잔여와 blocker를 명시한 뒤 별도 실행 |

일부 작업의 완료 보고·스크립트 존재·Run COMPLETED를 전체 품질 PASS로 바꾸지 않는다. 테스트 자산의 특정 Task List·인물·제목은 제품 요구사항이나 정답 사전으로 승격하지 않는다. Task 예정일과 실제 마감, 동일 command replay와 새 사용자 제출의 구분은 유지한다.

## 8. 문서와 Notion

각 원문은 자기 목적에 필요한 변경만 반영하고 기존 기능·정책 ID를 보존한다. 문서 버전끼리 연결하거나 기능 번호를 정책 번호와 묶지 않는다. 수정일은 문서 자체의 현재성을 표시하며 API/State/schema 버전과 연동하지 않는다.

Notion은 `MCP-Work-Agent → 번호순 주요 문서 → 같은 페이지의 읽기 쉬운 요약 + 원문 전체`를 유지한다. 이번에는 변경된 제품 원문 전체와 그 요약을 교체하고 이 기록을 90에 게시한다. 기존 기술 원문을 임의 수정하거나 별도 설명본을 새 authority로 만들지 않는다. 원문 게시 성공, 최종 본문 재조회 검증, 제품 E2E 완료는 서로 다른 상태로 보고한다.
