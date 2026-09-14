# Gmail 목록 metadata N+1 개선 실험

## 결론

| 항목 | 결과 |
| --- | ---: |
| 최종 선택 | **B20/W1** |
| Production Node p95 | 5,400.75ms → **1,987.24ms** |
| Production Node p95 개선 | **63.20%** |
| Local API p95 | 5,477.80ms → **1,750.28ms** |
| 물리 HTTP 요청 | 21회 → **2회** |
| 논리 Gmail API 연산 | 21회 → **21회** |
| 오류 / timeout / 403·429 | **0 / 0 / 0** |
| Provider WRITE/SEND | **0** |

실험 대상은 Gmail Thread 20개의 목록과 표시용 metadata 완성이다. 2026-06-01부터
2026-07-01까지의 고정 과거 구간에서 최초 20개 identity/order hash를 잠근 뒤 모든 trial의
count, 순서, metadata projection, next page token을 비교했다. 원문, Gmail ID, OAuth 정보는
결과에 저장하지 않았다.

## 상세 표

| 파일 | 내용 |
| --- | --- |
| [01-provider-candidate-matrix.md](01-provider-candidate-matrix.md) | 10개 Batch/Worker 후보 100회 비교 |
| [02-product-boundary-results.md](02-product-boundary-results.md) | Local API와 Production `execute_read_node` 결과 |
| [03-concurrency-and-resources.md](03-concurrency-and-resources.md) | J=2 응답성과 CPU·메모리·스레드 |
| [04-validation-and-scope.md](04-validation-and-scope.md) | 검증 수, 적용 범위, 제외 근거, 한계 |

## 제품 반영

| 호출 경로 | 반영 방식 |
| --- | --- |
| UI Google 메일 목록 | 기존 Local API → ConnectorReadPort → Google Workspace MCP → `gmail_search_threads` 경로에서 B20/W1 사용 |
| LangGraph Connector READ | Production `execute_read_node`가 같은 MCP operation과 B20/W1 사용 |
| query 검색 | query 유무와 무관하게 실제 반환된 Thread 수를 기준으로 B20 단위 분할 |
| 가변 결과량 | 0개는 detail 호출 없음, 1개는 단건 GET, 2~100개는 실제 개수만큼 최대 20개씩 순차 batch |
| metadata 비활성 조회 | detail/batch 없이 list 1회만 수행 |
| Gmail Draft full 조회 | 본문·첨부 크기가 가변이고 이번 metadata 실험 대상이 아니므로 기존 경로 유지 |

최신 원격 변경 `f0b0d4ce`를 병합한 통합 기준에서도 아래 회귀와 실제 제품 기동 검증을
통과했다. LangGraph 전용 복제 경로를 만들지 않고 UI와 Production Node가 동일한
`gmail_search_threads` authority를 사용한다.

## 재집계

```powershell
$result = "evaluation/results/gmail-metadata-hydration-20260914-7afac9f5"
.\.venv\Scripts\python.exe -m scripts.benchmark_gmail_metadata_hydration summarize-provider --result-dir $result
.\.venv\Scripts\python.exe -m scripts.benchmark_gmail_metadata_hydration summarize-backend --result-dir $result
.\.venv\Scripts\python.exe -m scripts.benchmark_gmail_metadata_hydration summarize-concurrent --result-dir $result
.\.venv\Scripts\python.exe -m scripts.benchmark_gmail_execute_read_node --result-dir "$result/node-session-003-fixed-june" --aggregate-only
```

초기에 사용한 변동 `최신 20개` 세션은 dataset drift 진단 자료로만 보존하며 위 결론과
통계에는 포함하지 않았다.
