# 04. 검증과 적용 범위

## 수행 수

| Lane | Warm-up | Measured | 유효 | 오류 | Dataset drift | WRITE/SEND |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Provider 10-config sweep | 50 | 1,000 | 1,000 | 0 | 0 | 0 |
| Local API A/B | 별도 warm-up | 200 | 200 | 0 | 0 | 0 |
| Production Node A/B | 10 | 200 | 200 | 0 | 0 | 0 |
| Local API J=2 | 별도 warm-up | 100 episodes / 200 jobs | 200 jobs | 0 | 0 | 0 |

## 가변 결과량 처리

| 실제 Thread 수 | Production 동작 | 상세 물리 HTTP 수 |
| ---: | --- | ---: |
| 0 | detail 생략 | 0 |
| 1 | 단건 metadata GET | 1 |
| 2~20 | 한 개 batch envelope | 1 |
| 21~40 | 20개 단위 두 batch, W=1 | 2 |
| 41~60 | 20개 단위 세 batch, W=1 | 3 |
| 최대 100 | 실제 반환 수만큼 `ceil(N/20)` batch | 최대 5 |

## 적용 여부

| 경로 | 판정 | 근거 |
| --- | --- | --- |
| 빈 query의 일반 Gmail 목록 | 적용 | `gmail_search_threads` 동일 hydration 경로 |
| Gmail query 검색 | 적용 | list query 이후 실제 반환된 ID만 동일 hydration |
| UI 자료 목록 | 적용 | Local API가 같은 ConnectorReadPort/MCP operation 사용 |
| LangGraph Connector READ | 적용 | Production Node 100/100 비교 완료 |
| metadata-disabled count traversal | 기존 최적 경로 유지 | 상세 호출 자체가 0회 |
| Gmail Draft full 검색 | 미적용 | 본문·첨부 payload가 가변이고 metadata-only 실험으로 안전성·16MiB envelope 여유를 입증하지 않음 |
| Calendar/Tasks/GitHub | 미적용 | Gmail batch endpoint와 다른 Provider 계약 |

## 안전과 한계

| 항목 | 결과 |
| --- | --- |
| Provider WRITE/SEND | 0 |
| rerun-to-pass | 0 |
| Raw Gmail ID/제목/본문 저장 | 0 |
| OAuth token/Authorization 저장 | 0 |
| 결론 범위 | 이 PC·계정·N=20 metadata fixture와 관측 기간 |
| p99 | 100회 표본의 참고값이며 안정적 tail 보장으로 해석하지 않음 |

## 최신 브랜치 통합 회귀

| 검증 | 결과 |
| --- | --- |
| 최신 원격 병합 기준 | `f0b0d4ce` → integration merge `30129382` |
| 직접 영향 Python 테스트 | 188 passed |
| 전체 Python 회귀 | 4,013 passed, warning 1 |
| Ruff / mypy | PASS / PASS (1,739 files) |
| Frontend 테스트 | 41 files, 267 tests passed |
| Frontend typecheck / lint / production build | PASS / PASS / PASS |
| 제품 readiness | 12/12 READY |
| 컴파일 UI | `/` 200, hashed JS 200 |
| 실제 UI·Connector READ | 실시간 연결 및 Gmail 목록 metadata 표시 확인 |
| 새 Graph Run / Provider WRITE·SEND | 0 / 0 |
