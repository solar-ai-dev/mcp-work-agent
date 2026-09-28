# 070 — 저장된 Query FIRST의 READ handoff component 통과

판단: **deterministic component PASS**. 새 Product 수정이나 모델 Trial이 아니다.
069의 실제 모델 결과를 원 Trial과 분리해 조회 인자·scope·cache·route/Work 경계까지
검증했다. RU 의미 오류나 최종 답변 품질이 해결됐다는 판정은 아니다.

실행 SHA `3e760b7992380420a9070fbfede8a70bbb8777d5`.
기준은 `070-query-read-handoff-criteria.md`, 실행은
`python -B -m scripts.verify_query_read_handoff`다. 전용 결과 폴더가 존재하면 재실행을
거절한다. 원066/069 DB·설정·checkpoint·raw는 수정하지 않았다.

## 실제 연결과 반례

| 경계 | 결과 |
| --- | --- |
| 069 FIRST → normalize/validator/build_query | 기존 materialized DETAIL_FETCH plan1과 동일 |
| exact ref → selected identity → Connector 인자 | 선택한 Task의 실제 ID·상위 목록 ID 보존, `tasks_get_task` |
| Registry → selected-resource scope → execute_read | 실제 Product owner를 통과하고 합성 snapshot READ1 |
| cache → acquisition → source-status projection | 같은 route의 `work-1`, COMPLETE, checked READ1 유지 |
| 목록 범위 밖 / 다른 계정 | PERMISSION_DENIED, 합성 dispatch 전 차단 |
| WRITE binding / 허용 Tool 제거 | 기존 owner에서 거절, 합성 dispatch 증가0 |
| 다른 Run의 cache 접근 | CROSS_RUN, entry 없음 |
| 다른 route / query의 cache 접근 | 각각 BINDING_MISMATCH, entry 없음 |
| 다른 route acquisition | 원 route는 NOT_ATTEMPTED/checked0. 다른 Work의 성공을 흡수하지 않음 |

정상 연결1과 음성 반례8이 통과했다. TaskList discovery route를 두 번째 업무 READ로
계산하지 않는다. 계정 getter는 역사적 선택 계정을 반환하는 **합성 context**이며 실제
Google 로그인·OAuth 권한 확인이 아니다. Connector만 로컬 fixture이고 나머지는 실제
normalize/validator/materializer/Registry/scope/READ/cache/projection 구현이다.

새 기본 in-memory component budget에서 connector1/detail1/source-page0/LLM0이다.
역사 Run budget을 복구·증가·재개한 결과가 아니다. Work 귀속은 Provider 응답이나 cache에
새로 만든 값이 아니라 frozen route에서 acquisition의 route ID로 결합한다.

## 검사·관측 보존

- 새 직접9 + 이전069 평가 도구14 = **23 PASS**.
- 기존 READ/인자변환/Work 연결45 + scope/cache22 = **67 PASS**. 이번 관련 검사 합90이며
  Canonical Case 성공률이나 전체 pytest 결과가 아니다.
- 새 runner Ruff/mypy PASS. 새 테스트 scoped mypy PASS(`--follow-imports=silent`).
- 합성 두 Work가 같은 READ를 공유하는 직접 검사도 dispatch1과 Work union을 유지했다.
  unknown Work ID는 실제 coverage 입력 검증기에서 거절한다.
- 독립 코드 검수에서 READ 후 coverage 실패 시 호출 관측이 누락될 수 있음을 발견했다.
  평가 도구만 보완해 각 READ 시도·예산·결과·예외·cache 응답을 후속 검증 전에 저장한다.
  실패를 성공으로 바꾸지 않고, 종료 해시 불일치도 FAIL/nonzero로 남긴다.
- 069 원 raw/plan, 066 checkpoint/DB/settings, Dataset/fixture, Product1110개 파일과
  gate 입력 결속은 시작·종료 동일하다. 비민감 요약만 버전관리한다.

raw: `evaluation/results/070-query-read-handoff/raw.json`
SHA256: `94ee673cc0f3883619826b26b6498e13f91aee2fc87950e0197b1c4c811eb19d`.

## 비용·남은 경계

신규 LLM calls/tokens/latency **0**, 외부 Provider READ/WRITE0, Approval0, Graph 실행0,
rerun-to-pass0. 로컬 snapshot READ1만 수행했다. 검증 전 GPU0MiB/0%/44°C,
여유 RAM 약19.6GiB였고 모델·pytest 병렬 실행이나 앱/서버 재시작은 없었다.
이는 한 시점의 자원 관측이며 peak 수치가 아니다.

Product/Prompt/Schema/State/Node/안전 계약 변경0. source-status 입력 projection을
검증했을 뿐 semantic Evidence 선택·Sufficiency 판단·Planning·Business 성공·Live Provider
권한·승인 후 실행을 시험하지 않았다. 현재 HEAD의 Canonical92 전체 품질도 미측정이다.

067–069에서 남은 Source 누락/오선택, Goal 조건 오염, 미요청 WRITE 의미, 금지/status
변형과 답변의 completion 상태 과잉해석은 그대로 남는다. 070은 기존 채택 Query 수정의
인접 연결 공백만 닫았으며 이 실패군에 대한 새 해결 가설을 제공하지 않았다.
따라서 069 checkpoint의 무근거 추가 탐색 판단은 유지한다. 같은 정보를 다른 Prompt
위치에 옮기거나 기존 실패 후보를 재실행하지 않았고 Epic 완료로 판정하지 않는다.
