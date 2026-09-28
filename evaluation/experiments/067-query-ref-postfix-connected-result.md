# 067 — MainGraph 종료 COMPLETED / 답변 PARTIAL / Query LLM 수정 미검증

## 실행과 판정

사전등록 HEAD `ca2a7b201cd2d076c018b6e0e1503d99dec4ba7d`, trial
`15e21382-1766-4e82-87dc-033a54c98dff`, Run `295775f3-0a64-4c3e-87ed-81fd37204421`.
기존 runner/actual Production MainGraph/candidate=None, CORE005 **1회**만 실행했다.
066 T3를 덮어쓰거나 새 Trial로 대체하지 않았다. runtime/environment bound에 걸리지 않았다.

- persisted Run `COMPLETED`, local snapshot Task GET1회, 미요청 Action 제안0.
- 답변: 선택 Task의 `needsAction`을 “진행 중”으로 표기하고 date-only 예정일8월10일을 반환.
  날짜는 정확하지만 needsAction은 미완료이며 실제 업무의 진행 상태까지 보장하지 않는다.
  **답변 의미 PARTIAL**, Runtime COMPLETED와 구분한다.
- RU CREATE 금지는 FIRST `NOT_FORBIDDEN`으로 누락됐다. 단순 상태 조회를
  `INCOMPLETE` Source filter로 좁힌 오류도 남아 **RU 의미 보존 PASS가 아니다**.
- Source TASK/SINGULAR/필수 정보 및 selected identity는 유지됐다. 실제 GET은 선택한
  동일 Task/parent를 사용했고 Evidence도 해당 snapshot에서 생성됐다.
- Query LLM 호출0. Output이 빈 목록이 되어 단일 selected deterministic READ를 탔다.
  따라서 `b7c449fa`의 exact-ref generation Schema를 실제 모델이 소비한 검증은 **미검증**이다.
  deterministic 경로 성공을 해당 수정의 모델 gate로 승계하지 않는다.

실제 model calls9, input27,809/output778 tokens, reported50,204ms/wall54,937ms,
usage 누락0. Live Provider READ/WRITE0, WRITE시도0, 승인/resume0, rerun-to-pass0.
generation 중 편집/pytest/다른 모델0. 종료 후 RAM여유16.17GiB,
GPU6385/8188MiB·사용률0%·53°C(peak 측정 아님).

## 066 T3와 처음 달라진 곳

7개 RU owner의 PromptRef/Schema/sampling options는 같다. Work FIRST는 input/wire/content까지
동일하다. **첫 input 차이는 Goal의 다음 두 필드뿐**이다.

| 필드 | 066 T3 → 067 |
| --- | --- |
| selected_resource_refs[0].resource_ref_id | 새 Run-local UUID. 실제 Provider ID/parent는 동일 |
| run_reference_time.reference_time | 2026-09-29 00:45:06 → 01:27:17, Asia/Seoul |

Goal input hash: `4263a961f7cb98a55d47233dc81d5421ca55773199ff2f89fbb8d6c3bcbdc2b4`
→ `4377c9703e243e279bff8425d90fe65ff29201eaea4349901216552c7a99127d`.

| owner | 실제 차이 |
| --- | --- |
| Goal FIRST | 이전 due 지시문·description의 내부필드 조각 대신 title/description 후보. 완료조건·business_concepts도 변경 |
| prohibition FIRST | CREATE FORBIDDEN → NOT_FORBIDDEN, 금지 의미 회귀 |
| Source FIRST | 입력은 달라졌지만 출력 내용 동일(TASK SINGULAR) |
| Output FIRST | TASK UPDATE/GMAIL SEND → 빈 Output, 이번에는 미요청 WRITE 의미 없음 |
| Route/Query | 같은 capability의 여러 경로를 거치던 이전과 달리 단일 selected Task READ, Query LLM0 |
| Planning | 실제 근거의 date-only는 보존, raw needsAction을 진행 중으로 과잉해석 |

이는 같은 wire의 순수 sampling variance 비교가 아니며, UUID와 시각 중 어느 것이
Goal 차이를 만들었는지도 분리되지 않았다. Query 수정이 RU를 개선했다는 인과 주장도 불가다.
Goal 슬롯 오염이 Output 오류의 원인이라는 가설은 아직 확정되지 않았다.

## 다음 근거와 한계

066에서 근거 없이 다음 RU 문구 변형을 하지 않기로 한 판단은 유지한다. 이번 새 연결
근거는 **Goal이 소비하는 임의 Run 식별자와 업무 의미의 표현 경계**를 좁게 조사할 이유다.
Goal 출력에는 selected-ref 선택 슬롯이 없고 실제 identity는 기존 deterministic owner가
원 WorkflowStartRequest에서 결속한다. request-local alias와 기준시각 영향을 비교할 경우
이 둘을 동시에 바꾸거나 native/parent ID까지 제거하면 안 된다. 효과는 미검증이다.

또한 `needsAction`의 의미 전달은 현재 canonical formatter가 이미 미완료로 처리하므로
답변 후 문자열 교정이나 Case Prompt를 추가하지 않는다. raw Evidence→compose owner에서
기존 Typed status를 활용할 수 있는지 확인하되 RU 금지 누락과 별개 문제로 기록한다.

## 결속과 원 기록

- Product tree `8e676676c445e1ba624bb0960f6b7800b1f6dd15951a70d59541c20d5fb19650`,
  end_binding unchanged=true. Prompt/Registry/runner hashes는066과 동일, Product tree/SHA는 다름.
- qwen3.5:9b/Ollama0.34.0/seed20260923/ctx16384/think=false. owner별 실제 sampler는 원 calls에
  보존하며 temperature 미전송을0이라고 하지 않는다.
- Dataset `f92603216a7f0a214bc72ce1f0301b64299e1ed2dbc59c6d20359ee053daa9d8`,
  fixture `59438f4fdd10d1037907f99d3445aac585857320774f89843b578b47c78fb37f`.
- `evaluation/results/067-query-ref-postfix-connected-t1/raw.json`:
  `d3cc865739d5671d0d0997d79472f9b28c21948041bbaa7968fb7f439db334ca`.
- 같은 폴더 `calls.json`:
  `dd9f77ae841d361d7e61200ed2b9ab4559c815f6a9ea70c338c022d06b4d84d2`.
- raw의 UNREVIEWED는 유지하며 이 문서가 별도 의미 검수다. 독립 검수도 동일 판정.

새 Product/Prompt 변경0. 현재 Canonical92 전체 및 반복 안정성/Live E2E 평가가 아니며,
단발 부분 답변을 전체 LangGraph 안정화로 보고하지 않는다.
