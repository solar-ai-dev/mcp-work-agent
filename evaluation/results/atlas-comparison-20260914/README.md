# Atlas Draft / Atlas q19 Run 비교

## 범위와 결론

- 기준 성공 SHA: `7afac9f55d329cb78ff1ed969cb8e9316c26fc1d`
- 기준 실패 SHA: `cfcf1faf8b4ae9d979cd6684bfd04f87d3ce17d5`
- 조사 시점 HEAD: `55f85993b1ee08a3a972e48b1bcfaa2f494ede61` (`cfcf1faf`보다 1 commit 앞섬)
- 이번 조사에서 제품 코드 변경, 새 Run, 승인 클릭, Provider WRITE/SEND는 모두 0이다.

| Case | 최초 차이 | 실제 실패 경계 | 원인 확정 여부 | 권장 수정 |
| --- | --- | --- | --- | --- |
| Atlas Draft | 실패 Run의 `max_source_page_calls=8` (성공은 50). 앞단 최종 Source/Output/route는 동일 | CALENDAR_EVENT container fan-out가 page 8회를 먼저 소비하여 TASK 및 discovery route는 0회 조회. `SOURCE_PAGE_LIMIT → REQUIRED_SOURCE_PARTIAL → CONTEXT_BLOCKED` | 실패 경로 확정. 왜 Smoke 설정이 50에서 8로 바뀌었는지는 기록 부재 | 우선 동일 page 상한으로 재비교. 제품 상한 8을 유지할 경우 container fan-out을 route-major가 아니라 required route 간 round-robin으로 배치하고 작은 상한의 starvation 회귀 테스트 추가 |
| Atlas q19 | raw goal과 최종 required-information 수가 달랐으나 frozen route와 초기 KEYWORD/ANY 형태는 동일. 최초 실패 유발 차이는 성공의 2번째 Gmail page가 exhausted였던 반면 실패는 3번째까지 `has_next_page=true`였던 점 | round 2에서 `CANDIDATE_DETAIL_REQUIRED`와 NEXT_PAGE를 가진 상태를 다시 허가한 뒤 4번째 semantic round 진입에서 `RetrievalRoundLimitExceeded` | 예외 producer/consumer와 accounting 불일치는 확정. 성공 당시 정확 query/Provider snapshot이 없어 더 앞선 query-vs-provider 원인은 미확정 | 실제 결정된 follow-up operation으로 budget을 승인하고, NEXT_PAGE가 4번째 round에 들어가기 전에 PARTIAL로 닫기. 이 최소 수정은 조사 시점 HEAD에 이미 존재하며 이번 작업에서는 변경하지 않음 |

## 확인 사실

1. 두 성공 Trace와 두 실패 Trace를 LangSmith의 기존 safe projection으로 읽었다. 원문 Prompt, OAuth/token, 메일 본문은 수집하지 않았다.
2. 두 Case 모두 `AGENT_SEARCH`, selected resource ref 0개, `qwen3.5:9b`, model digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`, `SIX_ROLE_BASELINE`, `resume-contract-v2`였다.
3. `7afac9f5..cfcf1faf`의 production diff는 ambiguity producer와 해당 Prompt/테스트뿐이다. Retrieval, Connector, fixture 코드는 바뀌지 않았다.
4. Prompt 조건은 완전히 같지 않다. `request_understanding.detect_ambiguity`가 성공의 `1.0.15/a0a56b...`에서 실패의 `1.0.17/5f90ba...`로 바뀌었다. `identify_goal 1.0.62`, `retrieval.plan_query 1.0.28`은 같았다.
5. 실제 historical temperature/seed는 safe Trace에 기록되지 않았다. 따라서 같은 값이었다고 단정하지 않았다. 저장소 launcher 기본은 temperature `0.0`, seed 미지정이며, request 단계 일부 Prompt는 코드에서 `identify_goal=0.1`, `identify_source_dependencies=0.05`, output/ambiguity=`0.0`으로 덮어쓴다. 이 값이 각 과거 프로세스에 실제 적용됐는지는 확인 불가다.

## Atlas Draft

성공과 실패 모두 raw `identify_goal`은 Source/Output을 직접 내지 않았지만, 최종 assembler는 `TASK + CALENDAR_EVENT`와 `GMAIL_DRAFT/CREATE`를 동일하게 만들었다. ambiguity raw owner도 둘 다 `CONNECTOR`였고 최종 ambiguity는 confirmation 불필요였다. 따라서 raw LLM 출력만으로 Source 결함이라 판정하지 않았다.

성공은 `calendar_list_events 23 + tasks_list_tasks 22 + calendar_list_calendars 1 + tasks_list_tasklists 1 = 47` READ 후 Evidence 3건, SUFFICIENT, WAITING_APPROVAL이었다. 실패는 page 상한 8에서 `calendar_list_events`만 8회 실행하고 모두 후보 0건이었다. 이후 세 route는 budget stop projection만 생겼고 실제 READ는 없었다. Context Retriever가 네 required route 모두 `REQUIRED_SOURCE_PARTIAL`로 만들었고 Main supervisor가 `CONTEXT_BLOCKED`를 생산했다.

## Atlas q19

성공은 Gmail search 2회(첫 page `has_next_page=true`, 둘째 `false`) 뒤 `gmail_get_thread` 12회, Evidence 10건, SUFFICIENT, 최종 답변으로 끝났다. 실패는 같은 KEYWORD/ANY 형태로 시작했지만 세 page가 모두 `has_next_page=true`였다. 각 page는 새 page-state hash를 가져 정상 pagination이었고, 2번째 page에서는 선택 Evidence 후보 2건이 교체됐다. 3번째 page에서는 선택 집합이 변하지 않았다.

실패 Run의 sufficiency는 매 회 `CANDIDATE_DETAIL_REQUIRED`였지만 결정적 planner는 `NEXT_PAGE`를 우선했다. cfcf의 assessor는 실제 계획이 아니라 미리 계산한 DETAIL_FETCH 수로 follow-up을 승인해 `additional_retrieval_rounds_used`가 0에 머물렀다. 실제 executor는 NEXT_PAGE를 semantic follow-up으로 계산해 round `0 → 1 → 2`를 사용했고, 다음 NEXT_PAGE에서 내부 `MAX_RETRIEVAL_ROUNDS=3` guard가 예외를 냈다. Source page(3/8), connector(3/50), detail(0/12) 상한은 소진되지 않았다.

## 확인 불가 / 추정 금지

- 성공 Trace의 요청 원문 bytes와 정확한 effective Gmail query는 safe projection에 없다. 의미 projection은 같은 Case임을 보여 주지만 byte-identical 요청·query라고 단정하지 않는다.
- 성공 당시 selected account/container 설정과 Provider snapshot은 Trace에 없어 실패 시점과 동일했다고 단정하지 않는다.
- q19의 더 앞선 차이가 unseeded LLM 변동인지 Provider 데이터 변동인지는 분리할 수 없다. 다만 실제 round 예외의 producer/consumer 불일치는 코드와 checkpoint로 확정했다.
- Atlas Draft가 route round-robin만으로 반드시 WAITING_APPROVAL에 도달한다고 단정하지 않는다. 해당 수정은 작은 상한에서 한 route가 다른 required route를 굶기는 결함만 닫는다.

## 추가 실행을 하지 않은 이유

기존 LangSmith Trace와 실패 Run checkpoint에 최초 budget/operation 차이, exact reason code, 실제 counter, connector 호출 순서가 모두 남아 있었다. 현재 HEAD는 실패 SHA보다 앞서 있고 q19 guard 수정도 포함하므로 새 Run은 cfcf 실패 조건의 재현이 아니며, historical Provider/query snapshot 공백도 복원하지 못한다.
