# 069 — Query exact-ref 수정: 실제 FIRST와 materializer 연결 통과

판단: **기존 `b7c449fa` 수정 유지 / 이번 단발 Query gate PASS**.
새 Product/Prompt/Schema 수정 없이 실행했으며, 전체 업무·반복 안정성 PASS는 아니다.

실행 SHA `64b30f999e30a008842f9b65906d112dabe916a1`, plan 파일 SHA256
`020e7509e70e24716de6821bfb5ddbad1f3689647ad60c3cd46d6e33188ec346`.
사전 기준은 `069-query-exact-ref-model-criteria.md`다.

## 같은 입력에서 최초 차이

원066 T3의 context_retriever step0 checkpoint를 read-only/query_only로 읽었다.
actual ToolRoutePlan의 TASK/TASK_LIST 및 work-1 binding, 선택 identity, 원 RequestIntent,
설정·예산·시각은 보존했다. 원 input/Prompt/모델/샘플링 wire를 그대로 재현하고,
DETAIL_FETCH ref의 자유 문자열을 기존 validator authority와 같은 exact-ref enum으로
바꾸는 채택된 Schema 차이 한 곳만 허용했다. coarse TASK 표기로 Route를 추정하지 않았다.

| 경계 | 이전066 | 현재069 |
| --- | --- | --- |
| LLM FIRST | native Task ID만 생성 | exact `task:<id>` 생성 |
| 정규화 | prefix 없는 값을 보존 | wire schema3→canonical schema2만 변환, exact ref 보존 |
| validator | `RETRIEVAL_ROUTE_SCOPE_VIOLATION`, detail_candidate_ref | 통과 |
| 실제 `build_query` | 진입 성공 없음 | 동일 frozen TASK Route/Connector/exact ref의 DETAIL_FETCH plan1 |
| 후속 모델 | semantic revision1도 같은 ref 오류 | revision 요청0, 신규 FIRST1만 실행 |

ref 접두어를 후처리하거나 ID를 발명하지 않았다. original input hash는
`38b954e7e9cc504b54a9150b36f91d7fb7acae0edfee5674f89d56377b8baf4e`이며 전체 deep equality다.
선택 Task를 직접 읽는 계획이므로 별도 TASK_LIST discovery를 이 라운드에 추가하지 않았다.
frozen Route와 work binding 자체를 삭제/합치거나 Source를 새로 판정한 결과가 아니다.

## 비용·안전·검사

| 실행 | calls | input/output tokens | reported ms |
| --- | ---: | ---: | ---: |
| 원066 FIRST — 재사용 | 1 | 5,486 / 167 | 10,208 |
| 원066 revision — 재사용 | 1 | 5,946 / 143 | 9,609 |
| 신규069 FIRST | 1 | 5,504 / 107 | 21,600 |

현재 cold load14,511ms, prompt eval3,575ms, generation3,442ms, HTTP wall21,640ms다.
로드 상태가 다르므로 역사 FIRST 대비 느려졌다는 후보 성능 결론을 내리지 않는다.
9B digest `6488c96f…`, Ollama0.34.0, ctx16384/seed20260923/think=false 유지.
temperature 미전송은 모델기본값1이며0이 아니다. usage 누락0, done=stop.

- 새 runner fake14 + 관련 Product Query/노드81 = **95 PASS**, Ruff PASS.
- runner mypy PASS. 새 테스트 파일은 `--follow-imports=silent`로 scoped PASS.
  전체 import checking에서는 기존 `tests/support/fakes/llm.py:287/293`의 두
  object→list 타입 오류가 남는다. 이를 수정하거나 전체 mypy PASS라고 주장하지 않는다.
- source/model/역사 authority 해시가 종료 후 모두 동일. 과거 DB·Run·budget 변경0.
  raw의 diagnostic_budget.llm_calls_used=7은 원 checkpoint의 복사값이며 이번 실제 호출 수가 아니다.
- 모델 동시1, 생성 중 편집/pytest/다른 모델0. 실행 전 GPU0MiB/44°C,
  종료 후6383MiB/0%/49°C(peak 아님). 프론트/백엔드/개인 process 변경0.
- Provider READ/WRITE0, 승인0, repair/retry/fallback0, rerun-to-pass0.

raw `evaluation/results/069-query-exact-ref-first-t1/raw.json` SHA256
`86335bcc9dac46eb9961dfa5e34e0eb31958ebd40595162a7eee77e22bd52735`.
첫 출력·정규화·actual consumer 결과를 분리 보존한다. 원066 실패 기록은 수정하지 않았다.
독립 검수도 같은 gate PASS다. 새 wire의 format/prompt.output_schema를 과거 Schema로
되돌리면 원 wire hash가 정확히 재현되는 것을 추가 모델 호출 없이 확인했다.

## 남은 경계

066의 미요청 TASK UPDATE/GMAIL SEND와 Goal 오염은 원 state에 그대로 남아 있다.
이번 Query gate는 이를 해결하지 않으며 새 MainGraph/Connector/Planning/Business 평가가 아니다.
067의 정확한 Task READ 후 needsAction을 진행 중으로 답하는 오류도 별개다.
Canonical92/Live Provider/승인 후 Execution·Verification/Release activation은 실행하지 않았다.

기존 RU·Planning 실패군을 다시 코드와 raw로 검토했지만 새 producer→consumer 손실은
확인되지 않았다. 068 fact 전달 실패가 아니라 실제 FIRST 의미 오류였다. 단순 enum 설명을
다른 위치로 옮기거나 fastpath completeness 검사를 약화하는 것은 새 인과 근거가 아니다.
이 결과를 전체 안정화 완료나 모델 능력 한계 확정으로 확장하지 않는다.
