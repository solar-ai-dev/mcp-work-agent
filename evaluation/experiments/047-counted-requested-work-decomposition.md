# 047 — Counted one-call requested-work decomposition

Issue: #287

## 범위

사용자 원문만 입력으로 받아 한 번의 LLM 호출에서 다음 세 값만 생성하는
evaluation-only 후보를 비교했다.

```text
user_request
→ work_count
→ WorkUnit[]
→ WorkRelation[]
```

후보는 먼저 독립적인 사용자 업무 결과의 개수를 판단하고, 그 수와 같은
WorkUnit을 작성하며, 한 업무의 요청된 결과가 다른 업무의 입력일 때만
`PROVIDES_INPUT_TO`를 작성한다. Tool 선택, Query 작성, Retrieval, Evidence,
실제 중간 산출물 생성, Planning, Provider I/O는 범위에 포함하지 않았다.

## 고정 조건

- Product HEAD: `5304dacd1aeef121a6b4690038e6c001fba5f142`
- Canonical 92 v8 SHA-256:
  `f92603216a7f0a214bc72ce1f0301b64299e1ed2dbc59c6d20359ee053daa9d8`
- Core 24 expectation SHA-256:
  `999322c76a7f090c8c9d83db93ebada850d5933176711c26d4158ec9e35506f2`
- Candidate Prompt SHA-256:
  `ef93d70434be72f0db9436797891e5e9005dac5ec13609e89d417460d4816cb0`
- Model: `qwen3.5:9b`
- Model digest:
  `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`
- temperature `0.0`, seed `20260920`, Case당 1회
- Core 24: 단순 17개, 복합 7개, 산출물 관계 필수 4개
- Holdout/Stress 미사용, Provider READ/WRITE `0`

## 결과

| 비교 | 전체 구조 | 단순 unit 수 | 복합 unit 수 | 관계 필수 Case | Schema | count=units | calls | tokens in/out | latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| flat baseline | 17/24 | 17/17 | 0/7 | 0/4 | 현재 계약 | 해당 없음 | 0 | 0 / 0 | 0ms |
| minimal v1 | 12/24 | 8/17 | 4/7 | 1/4 | 24/24 | 해당 없음 | 24 | 15,558 / 2,691 | 105,113ms |
| boundary-clarified v2 | 9/24 | 6/17 | 3/7 | 0/4 | 24/24 | 해당 없음 | 24 | 16,686 / 2,530 | 91,902ms |
| counted one-call | 13/24 | 11/17 | 2/7 | 2/4 | 24/24 | 24/24 | 24 | 18,726 / 2,717 | 105,382ms |

`counted one-call`은 v1 대비 6개 Case가 좋아지고 5개가 나빠졌다. v2 대비
7개가 좋아지고 3개가 나빠졌다. `work_count`와 생성된 WorkUnit 수는 항상
일치했지만, 이는 모델이 판단한 개수의 내부 일관성일 뿐 정답 업무 개수가
맞았다는 뜻은 아니다.

## 최초 의미 차이

- CORE-046은 `2 WorkUnit + 1 relation`으로 처음 정확히 분해됐다. 일정 생성
  결과가 안내 초안의 입력이라는 관계를 보존했다.
- CORE-009/012/020/021/026/036은 자료 확인·분석을 독립 결과로 승격해
  단일 업무를 두 개로 과분해했다.
- CORE-048/050은 서로 독립적인 세 결과 중 두 결과를 한 WorkUnit으로 합쳐
  `3 → 2`로 축소했다.
- CORE-054/059는 선행 결과와 후속 답장 업무를 하나로 합쳐 관계를 잃었다.
- CORE-056은 WorkUnit 수는 맞았지만, 두 번째 결과가 첫 번째 결과를 반드시
  소비한다고 해석해 요구되지 않은 relation을 만들었다.
- 구조가 맞은 CORE-001/010/027/041도 각각 다른 메일 검색 금지, 메일 내 지시
  무시, 일정 생성 금지, 새 항목 생성 금지를 objective에 명시적으로 보존하지
  않았다. 따라서 13/24는 전체 의미 정확도가 아니라 구조 상한이다.

최초 divergence는 Tool/Query/Retrieval이 아니라 동일한 one-call decomposition의
`work_count` 판단에서 발생했다. 숫자를 먼저 출력하게 한 Schema는 자기 일관성은
만들었지만, 독립 결과와 내부 처리 단계를 안정적으로 구분시키지는 못했다.

## 판단

- Candidate: `REJECT`
- RU 앞단 production Node 추가: `NO`
- #288 shared contract 변경: `NOT JUSTIFIED`
- Product State/Node/Edge/Schema/Prompt 변경: `0`
- rerun-to-pass: `0`

새 후보는 이전 v1/v2보다 전체 구조와 관계 회수는 소폭 좋아졌지만, v1이
보존하던 복합 업무 단위를 더 많이 잃었고 flat baseline의 단순 요청 안정성에도
미치지 못했다. 필요한 최소 규칙만 둔 one-call 구조에서도 같은 경계 오류가
반대 방향으로 반복되므로, 현재 Local Model에서 `work_count`를 앞에 추가하는
것만으로 RU production 앞단을 정당화할 수 없다.

Raw result:

- `evaluation/results/ru287-requested-work-counted-decomposition-core24-20260920/result.json`
