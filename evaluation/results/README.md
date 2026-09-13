# Evaluation 결과 인덱스

사람이 확인할 최종 평가·Smoke·원인 분석 결과는 이 디렉터리를 단일 보관 위치로 사용한다.
서버 PID, SQLite, stdout/stderr 같은 실행 상태는 `.runtime` 또는 `runtime`에 남기되 최종 결과로 취급하지 않는다.

## 최신 결과

| 날짜 | 목적 | 결과 묶음 | 핵심 판정 | ZIP |
| --- | --- | --- | --- | --- |
| 2026-09-14 | Issue 251 confirmed target contract 복구 | [issue251-confirmed-target-contract-20260914](issue251-confirmed-target-contract-20260914/README.md) | Product SHA 고정, Calendar Gate PASS 뒤 최종 6/6 PASS. rerun-to-pass 0, 승인·WRITE/SEND 0 | `summary.json` |
| 2026-09-14 | Issue 251 회귀 복구 6개 Production Smoke | [issue251-regression-smoke-six-20260914](issue251-regression-smoke-six-20260914/README.md) | 고정 SHA·각 1회: 3/6 PASS. Selected Event·Juniper EXHAUSTIVE·Atlas q19 통과, WRITE/SEND 0 | `summary.json` |
| 2026-09-14 | Atlas Draft·q19 성공/실패 Run 최초 차이 비교 | [atlas-comparison-20260914](atlas-comparison-20260914/README.md) | Draft는 source-page 8 제한에 따른 route starvation, q19는 실제 NEXT_PAGE와 budget 승인 operation의 불일치. 추가 Run 0, WRITE/SEND 0 | [다운로드](atlas-comparison-20260914.zip) |
| 2026-09-14 | Issue 251 Atlas 최소 수정 후 확인 | [issue251-atlas-postfix-20260914](issue251-atlas-postfix-20260914/README.md) | 저장 상한 8→50, 일반 사실 조회 detail 우선·EXHAUSTIVE pagination 유지. Atlas Draft WAITING_APPROVAL, q19 SUCCESS, WRITE/SEND 0 | `result.json` |

Atlas 비교 묶음은 다음 순서로 읽는다.

1. `README.md`: Case별 결론과 확인 사실/추정 구분
2. `comparison.json`: SHA, Run, 설정, 최초 차이의 구조화 기록
3. `cases/`: 직전 정상 출력, 실패 입력/출력, reason code, 코드 위치
4. `rounds.json`: q19의 round/query/candidate/evidence/counter 변화
5. `traces/`: 비교에 사용한 최소 안전 projection

## 기존 결과

| 날짜 | 분류 | 결과 묶음 | 요약 | ZIP |
| --- | --- | --- | --- | --- |
| 2026-09-13 | 전체 계약 감사 | [full-contract-audit-20260913](full-contract-audit-20260913/README.md) | 전수 감사와 후속 Smoke를 함께 기록. 최종 후속 측정 Business 3/6, Contract 6/6이며 전체 성공 판정은 NO | [다운로드](full-contract-audit-20260913.zip) |
| 2026-09-13 | 계약 감사 최종 POST Smoke | [contract-audit-post-smoke-six-20260913-final](contract-audit-post-smoke-six-20260913-final/README.md) | Business 1/6, Contract 3/6, WRITE/SEND 0 | [다운로드](contract-audit-post-smoke-six-20260913-final.zip) |
| 2026-09-13 | 계약 감사 POST Smoke | [contract-audit-post-smoke-six-20260913](contract-audit-post-smoke-six-20260913/README.md) | PRE 대비 Contract 1/6 → 3/6, Business 1/6 유지 | [다운로드](contract-audit-post-smoke-six-20260913.zip) |
| 2026-09-13 | 계약 감사 PRE Smoke | [contract-audit-pre-smoke-six-20260913](contract-audit-pre-smoke-six-20260913/README.md) | Business 1/6, Contract 1/6, WRITE 0 | [다운로드](contract-audit-pre-smoke-six-20260913.zip) |
| 2026-09-12 | Production Smoke 교정 후 1회 | [production-smoke-six-20260912-sequence-2](production-smoke-six-20260912-sequence-2/README.md) | 공식 6건 각 1회, Business 0/6, WRITE/SEND 0 | 폴더만 보존 |
| 2026-09-12 | Production Smoke | [production-smoke-six-20260912](production-smoke-six-20260912/README.md) | Business 2/6, 승인된 WRITE 1, 예상 밖 WRITE 0 | [다운로드](production-smoke-six-20260912.zip) |
| 2026-09-11 | Full Production E2E 중단본 | ZIP만 보존 | 사용자 중단 시점 자료이며 완료 결과로 해석하지 않음 | [다운로드](full-production-e2e-user-stopped-20260911.zip) |

## 보관 규칙

- 새 최종 결과는 `evaluation/results/<주제>-<YYYYMMDD>/`에 둔다.
- 사람이 읽는 진입점은 각 묶음의 `README.md`로 통일한다.
- 전달용 ZIP은 같은 이름으로 `evaluation/results/` 바로 아래에 둔다.
- 비밀키, OAuth 토큰, 불필요한 Provider 원문은 넣지 않는다.
- `.runtime`과 `runtime`에는 실행 중 상태만 두고 최종 보고서 사본을 남기지 않는다.
- `.runtime/reports`, `.runtime/results`, `runtime/reports`, `runtime/results`, `evaluation/reports`는 만들지 않으며 구조 Gate가 이를 검사한다.

## 결과가 아닌 것

| 종류 | 위치 | 이유 |
| --- | --- | --- |
| 제품 DB·LangGraph checkpoint·command replay·서비스 로그 | `runtime/<profile>/` 또는 기존 `.runtime/<profile>/` | 제품 실행 및 장애 복구 상태이므로 보고서와 분리 |
| 평가 입력 자료와 확인 기준 | `evaluation/datasets/`, `evaluation/checks/` | Run 결과가 아니라 재현 입력 |
| Prompt 후보 | `evaluation/prompt_candidates/` | 활성 제품 Prompt나 실험 결과가 아닌 변경 후보 |
| 장기 실행 요약 | `evaluation/실행기록.md` | 날짜/커밋/변경/결과를 잇는 canonical 기록 |
