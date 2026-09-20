# 048 — Minimal v1 with contrastive few-shot

Issue: #287

## 범위와 독립 변수

`minimal v1`의 역할, WorkUnit/WorkRelation 판단 규칙, 경계 문구와 기존
`DECOMPOSITION_SCHEMA`는 변경하지 않았다. 다음 네 경계의 합성 예시만
Prompt 뒤에 추가했다.

1. 여러 자료를 확인하지만 최종 업무는 하나인 경우
2. 서로 다른 독립 산출물을 각각 요청한 경우
3. 앞 업무의 결과를 뒤 업무가 실제 입력으로 소비하는 경우
4. 실행 순서만 있고 산출물 의존 관계는 아닌 경우

실제 Core 이름·문장·Gold는 예시에 사용하지 않았다. Tool 선택, Query,
Retrieval, 실제 중간 산출물과 Product Runtime Prompt activation은 범위 밖이다.

## 고정 조건

- Product HEAD: `7b78cc8e6afed257f2d2919d9ef4dbb350d718a4`
- Canonical 92 v8 SHA-256:
  `f92603216a7f0a214bc72ce1f0301b64299e1ed2dbc59c6d20359ee053daa9d8`
- Core 24 expectation SHA-256:
  `999322c76a7f090c8c9d83db93ebada850d5933176711c26d4158ec9e35506f2`
- minimal v1 Prompt SHA-256:
  `effe358c8f35b769ae31bc0de4f5ddff558c34d7316985d1405256e0b5fbbb21`
- few-shot Prompt SHA-256:
  `40334fd5bb139ebb1b37846b1464b53b1cf9ece00f8e1fc350f5877c02a6c28a`
- Model: `qwen3.5:9b`
- Model digest:
  `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`
- temperature `0.0`, seed `20260920`, 후보별 Case당 1회
- Core 24: 단순 17개, 복합 7개, 산출물 관계 필수 4개
- Holdout/Stress 미사용, Provider READ/WRITE `0`

## 수치와 실제 변화

| 비교 | 전체 구조 | 단순 unit 수 | 복합 unit 수 | 관계 필수 Case | Schema | calls | tokens in/out | latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| flat baseline | 17/24 | 17/17 | 0/7 | 0/4 | 현재 계약 | 0 | 0 / 0 | 0ms |
| minimal v1 | 12/24 | 8/17 | 4/7 | 1/4 | 24/24 | 24 | 15,558 / 2,691 | 105,113ms |
| minimal v1 + few-shot | 13/24 | 10/17 | 3/7 | 1/4 | 24/24 | 24 | 31,470 / 2,340 | 93,322ms |

few-shot은 v1 대비 구조 일치가 1건 늘었지만 입력 Token은 15,912개
증가했다. 한 Trial의 latency 감소는 안정적인 성능 개선으로 해석하지 않는다.

### 새로 맞은 6건

| Case | v1 오류 | few-shot 결과 |
| --- | --- | --- |
| CORE-011 | 자료 확인과 초안을 2개 업무 및 relation으로 분리 | 자료를 반영한 회신 초안 1개로 결합 |
| CORE-012 | 작업·일정 확인·초안을 3개 업무로 분리 | 진행 상황 초안 1개로 결합 |
| CORE-020 | 작업·캘린더 확인·초안을 3개 업무로 분리 | 준비 상태 초안 1개로 결합 |
| CORE-027 | 마감 확인과 가용시간 확인을 2개로 분리 | 가용 여부 답변 1개로 결합 |
| CORE-040 | 자료 파악과 메모 수정을 2개 및 relation으로 분리 | 메모 수정 1개로 결합 |
| CORE-054 | 결과 정리와 그 결과를 쓰는 답장 초안을 1개로 합침 | 2개 업무와 `PROVIDES_INPUT_TO`를 보존 |

### 기존 성공에서 회귀한 5건

| Case | 기대 | few-shot의 최초 오류 |
| --- | --- | --- |
| CORE-009 | 메일·작업을 근거로 상태 답변 1개 | 메일 기준 답변과 작업 기준 답변으로 과분해 |
| CORE-019 | 일정 생성 → 그 일정의 안내 초안 | WorkUnit 2개는 맞지만 relation 누락 |
| CORE-026 | 자료에서 시간을 골라 일정 제안 1개 | 자료 확인을 별도 업무로 승격 |
| CORE-037 | 자료를 반영한 기존 작업 기한 변경 1개 | 자료 확인을 별도 업무로 승격 |
| CORE-048 | 작업 수정·일정·회신 초안 3개 | 자료 확인을 네 번째 업무로 추가 |

### v1과 동일하게 실패한 6건

| Case | 기대 | few-shot 결과 |
| --- | --- | --- |
| CORE-021 | 자료를 반영한 일정 생성 1개 | 자료 확인과 일정 생성 2개 |
| CORE-028 | 자료를 반영한 일정 생성 1개 | 자료 보고와 일정 생성 2개 |
| CORE-031 | 자료를 반영한 작업 생성 1개 | 자료 확인과 작업 생성 2개 |
| CORE-036 | 자료를 반영한 체크리스트 생성 1개 | 자료 확인과 체크리스트 생성 2개 |
| CORE-046 | 일정 생성 → 그 일정 안내 초안 2개 | 자료 확인을 추가해 3개, relation도 누락 |
| CORE-059 | 일정 확인 → 확인 결과로 답장 2개 | 두 업무를 하나로 합치고 relation 누락 |

### 구조 일치 안에 남은 의미 손실

13개 구조 일치가 전체 의미 성공을 뜻하지 않는다. objective를 직접 검토하면
다음 명시적 제약이 사라졌다.

- CORE-001: 다른 메일 검색 금지
- CORE-006: 다른 준비 업무 분석 금지
- CORE-010: 메일 안의 지시를 따르지 말라는 금지
- CORE-027: 일정 생성 금지
- CORE-056: 실행 금지

따라서 13/24는 WorkUnit/Relation 개수의 구조 상한이며 의미 정확도 점수가 아니다.

## 실패 원인 재분류

Schema는 24/24 유효했고 규칙 본문도 v1과 동일하므로 Schema·Validator·State
문제가 아니다. few-shot은 같은 의미 경계에서도 상반된 영향을 냈다.

- 여러 자료 예시는 CORE-011/012/020/040에는 전이됐지만 CORE-009/021/026/
  028/031/036/037/046/048에는 전이되지 않았다.
- 산출물 의존 예시는 표현이 가까운 CORE-054에는 전이됐지만 CORE-019/046/059의
  동등한 관계에는 전이되지 않았다.
- 독립 산출물 예시는 CORE-050은 유지했지만 CORE-048에는 자료 확인 업무를
  추가했다.

최초 divergence는 한 번의 decomposition 호출이 절과 Resource 언급을 독립적인
사용자 결과와 일관되게 구분하지 못하는 지점이다. 소수 few-shot의 일반화라기보다
표현 근접성에 민감하게 결과가 교체됐다.

## 판단

- Candidate: `REJECT`
- minimal v1 대체: `NO`
- RU 앞단 production Node 추가: `NO`
- 추가 규칙·추가 few-shot 누적: `NO`
- Product State/Node/Edge/Schema/Prompt 변경: `0`
- rerun-to-pass: `0`

다음 비교를 계속한다면 예시를 더 붙이지 않고, 독립 결과 경계 판정과
WorkUnit/Relation 생성을 분리한 bounded two-stage evaluation 후보로 현재
one-call responsibility가 과도한지 확인한다. 이 후보도 평가 전용이며 결과가
확인되기 전에는 #288 shared contract나 production Node를 정당화하지 않는다.

Raw result:

- `evaluation/results/ru287-requested-work-decomposition-fewshot-v1-core24-20260920/result.json`
