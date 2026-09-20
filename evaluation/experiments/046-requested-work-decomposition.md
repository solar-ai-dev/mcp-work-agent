# 046 — Requested Work decomposition

Issue: #287

## 범위

이번 실험은 Request Understanding 앞단의 다음 경계만 비교했다.

```text
user_request
→ WorkUnit[]
→ WorkRelation[]
```

Tool 선택, Query 작성, Retrieval, Evidence, 실제 중간 산출물 생성, Planning,
Provider READ/WRITE는 실행하지 않았다. Schema는 `unit_id`, `objective`,
`PROVIDES_INPUT_TO` relation endpoint만 가진다.

044의 WorkUnit 결과는 Output Resource/effect pair 실험으로, 045는 실제 산출물
materialization/consumer handoff 실험으로 재분류했다. 두 결과는 이번 최소
decomposition의 채택·기각 근거에 합산하지 않는다.

## 고정 조건

- Product HEAD: `ed3aa3c96c759a2d2d2fc83a224b3cbebaad2a21`
- Canonical 92 v8 SHA-256:
  `f92603216a7f0a214bc72ce1f0301b64299e1ed2dbc59c6d20359ee053daa9d8`
- Model: `qwen3.5:9b`
- Model digest:
  `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`
- temperature `0.0`, seed `20260920`, 후보별 Case당 1회
- expectation SHA-256:
  `999322c76a7f090c8c9d83db93ebada850d5933176711c26d4158ec9e35506f2`
- v1/v2 Prompt SHA-256:
  `effe358c8f35b769ae31bc0de4f5ddff558c34d7316985d1405256e0b5fbbb21` /
  `b3d968b07359d4caae03adb3298224f0605d25c8a6e557614ec74e3dde6324f4`
- Core 24: 6개 Canonical category에서 4개씩 선택
- Holdout/Stress 미사용, Provider READ/WRITE `0`

## 사전 기대 경계

- 단일 사용자 결과를 위한 자료 확인·비교는 별도 WorkUnit이 아니다.
- 서로 다른 요청 결과는 별도 WorkUnit이다.
- 명시적으로 만든 변환 결과를 후속 업무가 소비하면 두 WorkUnit과
  `PROVIDES_INPUT_TO` 관계다.
- 평가 대상 24개 중 단순 17개, 복합 7개, 산출물 관계 필수 4개다.

현재 flat `RequestIntentV2` baseline은 WorkUnit/Relation 표현이 없어 모든 요청을
하나의 단위로 본다. 따라서 단순 요청 구조는 `17/17`, 복합 업무 단위는 `0/7`,
산출물 관계는 `0/4`다.

## 결과

| 비교 | 전체 구조 | 단순 unit 수 | 복합 unit 수 | 관계 필수 Case | Schema | calls | tokens in/out | latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| flat baseline | 17/24 | 17/17 | 0/7 | 0/4 | 현재 계약 | 0 | 0 / 0 | 0ms |
| minimal v1 | 12/24 | 8/17 | 4/7 | 1/4 | 24/24 | 24 | 15,558 / 2,691 | 105,113ms |
| boundary-clarified v2 | 9/24 | 6/17 | 3/7 | 0/4 | 24/24 | 24 | 16,686 / 2,530 | 91,902ms |

v1은 복합 업무 단위를 baseline보다 많이 보존했지만, 단순 요청 17개 중 9개를
과분해했다. v2는 종속 자료 확인을 별도 업무로 만들지 말라는 일반 경계를
명확히 했지만 단순 요청 과분해가 11개로 늘었고 필수 산출물 관계는 모두
누락했다.

Raw result:

- `evaluation/results/ru287-requested-work-decomposition-core24-20260920/result.json`
- `evaluation/results/ru287-requested-work-decomposition-v2-core24-20260920/result.json`

대표 최초 divergence:

- CORE-012: 법무 작업과 캘린더 확인을 각각 독립 WorkUnit으로 만들고 메일 초안과
  관계를 만들지 않았다. 하나의 진행 상황 초안을 위한 입력 자료를 업무 결과로
  승격했다.
- CORE-046: 일정과 안내 초안 두 WorkUnit은 보존했지만, “그 일정”이 후속 초안의
  입력이라는 관계를 누락했다.
- CORE-054/059: 명시적 선행 결과와 후속 작성·전송을 하나의 WorkUnit으로 합쳐
  산출물 관계를 잃었다.
- CORE-001/010 등 일부 구조 일치 결과도 다른 Source 검색 금지, 메일 내 지시 무시
  같은 조건을 objective에 온전히 보존하지 않았다. 구조 수치가 전체 의미 성공을
  뜻하지 않는다.

## 판단

`WorkUnit[] + WorkRelation[]`라는 최소 Schema 자체는 모든 Case에서 유효한 JSON을
받았다. 그러나 현재 Local Model/Prompt 후보는 업무 경계를 안정적으로 만들지 못했다.
실패는 Tool·Query·Retrieval·산출물 materializer의 복잡성 때문이 아니라 첫
decomposition call에서 발생했다.

- 현재 후보: `REJECT`
- RU 앞단 production Node 추가: `NO`
- #288 shared contract 변경: `NOT JUSTIFIED`
- #294 Prompt/Few-shot 확대: 이번 후보를 채택하지 않았으므로 미진행

더 무거운 two-stage parse나 사례 예시를 추가하면 이번 질문과 독립 변수가 달라진다.
현재 결과만으로는 flat baseline의 단순 요청 안정성을 희생하면서 decomposition Node를
추가할 가치가 없다. Product State/Node/Edge/Schema/Prompt 변경은 `0`이며
rerun-to-pass와 Provider READ/WRITE도 `0`이다.
