# 02. 제품 경계 결과

## Local API

| Config | 유효 Trial | 평균 (ms) | p50 (ms) | p95 (ms) | 평균 CPU (ms/job) | 오류율 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| S3 baseline | 100/100 | 4,755.06 | 4,701.34 | 5,477.80 | 545.16 | 0% |
| **B20/W1** | **100/100** | **1,310.06** | **1,170.80** | **1,750.28** | **159.84** | **0%** |

| 비교 | 결과 |
| --- | ---: |
| paired p95 감소 | 3,727.52ms |
| paired p95 개선 | 68.05% |
| 개선율 95% CI | 61.07% ~ 70.07% |

## Production `execute_read_node`

측정 경계는 `execute_read_node → retrieval.execute_read → ConnectorReadPort → Google
Workspace MCP → gmail_search_threads → Google Provider → RunRetrievalCache → node 반환`이다.
Upstream LLM/Agent는 실행하지 않았다.

| Config | 유효 Trial | 평균 Node (ms) | p50 Node (ms) | p95 Node (ms) | 평균 MCP (ms) | 평균 Provider (ms) | 평균 HTTP |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| S3 baseline | 100/100 | 4,650.62 | 4,512.48 | 5,400.75 | 4,650.48 | 4,647.27 | 21 |
| **B20/W1** | **100/100** | **1,563.10** | **1,502.76** | **1,987.24** | **1,562.95** | **1,560.13** | **2** |

| 계약 비교 | S3 | B20/W1 |
| --- | ---: | ---: |
| Node COMPLETE | 100/100 | 100/100 |
| provider_called | 100/100 | 100/100 |
| resource count/identity/order | 100/100 | 100/100 |
| metadata projection | 100/100 | 100/100 |
| next_page_token | 100/100 | 100/100 |
| dataset drift / silent partial | 0 / 0 | 0 / 0 |
