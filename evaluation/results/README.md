# Evaluation Results

이 디렉터리는 새 실험·Smoke·진단 실행 결과의 로컬 저장 위치다.
`<주제>-<YYYYMMDD>/`와 필요한 전달용 ZIP만 생성하며 Git에는 커밋하지 않는다.

과거 원시 결과와 누적 실행 기록은 Canonical v8의 활성 평가 기준이 아니므로
정리되었고 Git history에서만 복구할 수 있다. 제품 기준점 요약은
[`../experiments/000-baseline-smoke-deed5275.md`](../experiments/000-baseline-smoke-deed5275.md)에 남긴다.

이번 Gmail 묶음은 사용자가 원격 공유를 명시한 전달 예외다. 비식별 README·요약 표와
결과 ZIP만 추적하며, 재실행용 원시 로그는 계속 gitignored 로컬 영역에 둔다.

| 날짜 | 목적 | 결과 묶음 | 핵심 판정 | ZIP |
| --- | --- | --- | --- | --- |
| 2026-09-14 | Gmail Thread 목록 metadata N+1 개선 | [gmail-metadata-hydration-20260914-7afac9f5](gmail-metadata-hydration-20260914-7afac9f5/README.md) | B20/W1 선택, Production Node p95 63.20% 개선, WRITE/SEND 0 | [다운로드](gmail-metadata-hydration-20260914-7afac9f5-result-bundle.zip) |
