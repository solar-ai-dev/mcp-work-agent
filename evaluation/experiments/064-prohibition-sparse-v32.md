# 064 v32 — Sparse 명시금지 표현 사전계획

## 원인 근거와 후보 축

v31의 동일 6개 입력 paired sampler 비교에서는 default 1과 explicit 0 모두 owner 기대가
3/6만 충족됐다. 005/027은 CREATE 금지를 계속 누락했고 056은 0에서도 SEND만 금지했다.
027은 원문·Work span·Goal·business concept 모두에 금지가 있어 Goal 누락 하나로 설명할 수 없다.
실제 Product system/schema/wire hash도 일치했으며 FIRST 12개가 구조적으로 유효했다.

현재 표현은 지원되는 네 effect마다 FORBIDDEN/NOT_FORBIDDEN과 Work 귀속을 생성하지만,
기존 Goal 정규화는 최종적으로 FORBIDDEN 항목만 보존한다. 이번에는 동일 semantic owner가
그 정규화된 모양에 대응하는 sparse 명시금지 목록을 직접 생성하도록 비교한다.
이는 온도나 Goal 제거 실험이 아니라 **출력 표현 및 그 표현에 맞는 owner 설명의 일관된 후보**다.
성공할 것이라는 결론이나 모델 한계 주장은 하지 않는다.

## 변경·불변 경계

- 기존 v31의 6개 frozen actual input을 모두 그대로 사용한다. 원문/Goal/Work/selected refs/
  effect 후보/시간을 고치지 않는다. Case 및 Work 개수 자체는 정답이 아니다.
- 동일 owner 한 번의 FIRST, default sampling temperature 미전송(실제 모델 기본값 1).
  seed 20260923, think false, context 16384, timeout 180초는 v31과 같다.
- 출력: `effect_prohibitions: [{effect, work_unit_ids}]`. 빈 목록과 복수 effect,
  한 effect에 복수 현재 Work ID를 허용한다. 같은 effect 중복은 허용하지 않는다.
- 효과/Work는 기존 후보의 closed ID만 쓴다. Resource-qualified scope, 키워드 분기,
  Few-shot, 새 업무 의미 owner, 자동으로 금지를 채우는 validator를 추가하지 않는다.
- 금지 여부는 모델이 판단한다. 입력에 명시 금지가 있어도 빈 목록은 구조적으로 유효하고
  의미 평가는 실패로 남는다. 구조적 통과를 의미적 통과로 대신하지 않는다.
- 출력형상에 맞는 간단한 후보 설명은 evaluation 모듈의 `SOURCE` 상수에 격리한다.
  Product-wide context와 입력 assembly는 그대로 사용한다. Product Prompt/manifest/registry,
  Product source, State/Graph/Approval/Execution 계약은 수정·활성화하지 않는다.

Candidate ID: `sparse-effect-prohibitions-v32`.
평가 PromptRef version: `evaluation-sparse-v32`; content hash는 실제 `SOURCE` bytes에서 생성.
Output schema version: `evaluation-sparse-prohibitions-v1`; Work ID별 실제 schema hash를 결속한다.
원래 Product PromptRef와 후보 PromptRef를 계획/실제 wire에 구별해 기록한다.

## 기존 consumer 연결

검증된 sparse 항목에는 구조상 명시금지라는 `prohibition=FORBIDDEN`만 붙인다.
NOT_FORBIDDEN 행을 발명하거나 Work ID를 추정·union하지 않는다.
기존 `validate_request_goal_candidate` 정규화가 동일 effect/Work 목록을 보존하는지 확인한다.
이 component probe의 Source/Output responsibilities는 빈 값이며 실제 업무 완료나 Graph 실행이 아니다.

직접 테스트에서는 실제 `validate_output_responsibility_candidate`와 현재 signed Registry 후보를
사용해 같은 Work의 금지 효과는 거절하고, 다른 Work의 동일 effect는 허용하는지 검증한다.
READ-source 제외 control의 빈 목록도 허용한다. 이는 잘못된 모델 의미를 고치는 연결이 아니라,
모델이 만든 명시금지를 기존 consumer가 같은 의미로 받는지 보는 검증이다.

## Baseline 재사용과 호출 상한

Baseline은 v31의 `model_default` 6행만 재사용한다.
raw bytes SHA-256: `97ea14004f5c4d4a37e298f8474d1ccb0f564bd4c80e47944f6e4fd6b7beee39`.
061/062의 예전 점수, v31의 zero arm, 실제 MainGraph 성공/실패 점수는 재사용하지 않는다.

재사용 전 정확한 raw hash, 모델 digest/show parameters, Dataset/Fixture/frozen inputs,
Product PromptRef, 관련 Product 코드 및 v31 harness hash, Case별 실제 input/schema/system
hash와 temperature 옵션 미전송/seed/context/think를 검사한다. 달라지면 실행을 거절한다.
global manifest/input-contract 파일에 다른 owner 변경이 있어도 해당 prohibition slot과
전역 forbidden-input 계약을 이전 HEAD의 파일과 비교하고, 해당 owner의 실제 assembled
system/input/schema가 같아야 한다. 전체 HEAD가 같다고 허위 기록하지 않고 origin/current를 남긴다.
관련 consumer 코드 hash는 후보 계획에 추가 결속한다.

후보 호출은 6 FIRST, Case별 schema repair 최대 1회, **신규 실제 호출 최대 12회**다.
Product repair envelope와 scope guard를 재사용하며 semantic revision/transport retry/rerun-to-pass는 0.
각 FIRST/repair/raw/validation/normalization/실제 wire options/calls/tokens/latency를 보존한다.
usage 누락은 0 token의 완전 관측으로 처리하지 않는다. 실패를 성공 Trial로 교체하지 않는다.

## 채점과 한계

v31의 원문·Canonical Gold 기반 effect 기대를 그대로 쓴다. 의미 판정은 effect 집합의
누락·발명과 Case별 설명이며, closed Work binding은 별도 구조 검사다.
이 집합은 모든 multi-work 의미 귀속/조건부·인용 금지/Resource-qualified 금지를 검증하지 않는다.
035의 기존 WorkUnit 2개 입력도 그대로 유지한다. 같은 숫자라도 어떤 금지가 회복되거나
새로 발명됐는지 함께 보고한다. owner 성적을 최종 업무 성공률로 승계하지 않는다.

## 실행과 준비 검증

실행자는 다른 모델 Trial과 겹치지 않게 먼저 현재 코드·HEAD를 동결한다.

```powershell
.venv/Scripts/python.exe -m scripts.evaluate_sparse_effect_prohibitions --result-dir evaluation/results/064-prohibition-sparse-v32-t1
```

위 명령은 model catalog/show 조회와 사전계획 생성만 한다(generation 0).
출력된 normalized plan SHA를 그대로 사용한다.

```powershell
.venv/Scripts/python.exe -m scripts.evaluate_sparse_effect_prohibitions --result-dir evaluation/results/064-prohibition-sparse-v32-t1 --execute-plan evaluation/results/064-prohibition-sparse-v32-t1/preregistered-plan.json --expected-plan-sha256 <출력된 SHA>
```

계획·raw·trial claim은 exclusive 생성하여 동일 Trial 재실행을 막는다.
준비 직접 테스트: 새 후보 23개 + 기존 sampler 16개 + 관측 13개 = **52 PASS**.
빈/복수 effect·복수 Work·잘못된 ID·다른 Work 안전 반례·wire 동일 입력·bounded repair·scope
보존·기존 baseline 재사용 mismatch 검사를 포함한다. 준비 단계 모델 generation/Provider/제품 변경은 0.
아직 실제 모델 후보 성적이나 Production 채택을 주장하지 않는다.
