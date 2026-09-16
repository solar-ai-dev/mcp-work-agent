# Evaluation Results

이 디렉터리는 제품 Smoke, 성능 실험, Canonical 평가 결과의 로컬 저장 위치다.
최종 결과는 아래 표에서 바로 열고, 중간 실행은 개별 폴더로 늘리지 않는다.

## 결과 요약

| 구분 | 최신 결과 | 핵심 판정 | 상세 |
| --- | --- | --- | --- |
| Production Smoke | 2026-09-14 / `7afac9f5` | Business `4/6`, Contract `4/6`, WRITE/SEND `0` | [최종 6건](01-production-smoke/03-final-smoke-20260914-7afac9f5/final-smoke-six/README.md) |
| Production 실패 분석 | 2026-09-13 / `768b12ab` | 재실행 없이 실패 4건의 최초 노드·직전 노드·원인 분석 | [분석](01-production-smoke/01-failure-analysis-20260913-768b12ab/README.md) |
| Gmail metadata 성능 | 2026-09-14 / `7afac9f5` | `B20/W1` 선택, Production Node p95 `63.20%` 개선, WRITE/SEND `0` | [결과](gmail-metadata-hydration-20260914-7afac9f5/README.md) · [ZIP](gmail-metadata-hydration-20260914-7afac9f5-result-bundle.zip) |
| Canonical 92 | 2026-09-15 / `5a49aa00` | 92건 1회 완료: PASS `8`, PRODUCT_FAIL `82`, 개별 Harness 제한 `2` | [본평가](02-canonical92/01-full-run-20260915-5a49aa00/README.md) · [ZIP](02-canonical92/01-full-run-20260915-5a49aa00.zip) |
| Canonical 후속 분석 | 2026-09-15 / `fe71f4ac` | CORE-005/006/008 최초 분기와 최종 Live 검증 분리 | [최종 검증](02-canonical92/03-final-live-validation-20260915-fe71f4ac/README.md) · [최초 분기](02-canonical92/02-first-divergence-20260915-f0c47aa4/README.md) |
| Terminal 응답 분석 | 2026-09-14 | LLM 응답 실패 경계 및 측정 결과 | [보고서](01-production-smoke/04-terminal-response-llm-20260914/report.md) · [ZIP](01-production-smoke/04-terminal-response-llm-20260914.zip) |

## 폴더 규칙

- `01-production-smoke/`: 제품 Smoke, 안정화, 실패 분석
- `02-canonical92/`: 최신 본평가와 직접 원인 검증
- `gmail-metadata-hydration-20260914-7afac9f5/`: 벤치마크 스크립트가 참조하는 고정 성능 결과 경로
- `02-canonical92/90-superseded-runs-20260914-20260915.zip`: 정리 전 diagnostic, probe, 중단본 23개를 묶은 복구용 보관본

새 실행은 `<주제>-<YYYYMMDD>-<짧은 SHA>` 형식을 사용한다. 같은 목적의 diagnostic이나
probe가 반복되면 최종본만 노출하고, 중간본은 하나의 `90-superseded-runs-*.zip`으로 묶는다.
원시 Gmail ID, 본문, OAuth Token, Authorization Header는 저장하지 않는다.
