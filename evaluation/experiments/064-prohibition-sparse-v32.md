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

## 실제 실행 결과 — 2026-09-28

**Sparse 표현만으로는 금지 누락 복구가 끝나지 않았다. Production 채택은 하지 않는다.**
owner 기대 충족은 v31 default 3/6 → v32 3/6이고, 여전히 005/027/056이 미충족이다.
다만 056에서 SEND/UPDATE/DELETE 금지가 실제 첫 출력에서 회복됐다. CREATE만 남아,
점수만 같다고 표현 효과가 전혀 없다고 결론내리거나 반대로 복구 완료라고 주장하지 않는다.

### 실행 결속과 원시 관측

- 실행 HEAD: `b0033565ab54e94a3fc911163361a6c2a941b9cf`.
- raw: `evaluation/results/064-prohibition-sparse-v32-t1/raw.json`.
- raw bytes SHA-256: `358ad42822b4b4c020b75d7df26db4872d9a155f2727df12e4dc8975b058f77d`.
- 사전계획 bytes SHA-256: `c3318de0cd0afe1d665c01afad32b7e896d02e21b95738a5f2f50daaffd54c12`.
- 후보 source/Prompt hash: `b380e0f384c8a017e5fb7837754f3fe994d1b17cfc588ca23f96656994b9337c`.
- 후보 module hash: `f9f6bfa629675714f26e356c2f58f46da2d1bcffb6e011187e0b61b5c89e1580`.
- 모델 digest: `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`.
  모델 기본값 temperature 1 / top_k 20 / top_p 0.95 / presence_penalty 1.5 그대로다.
- Baseline origin HEAD는 `a458d9aca7600b1d59233f212641fc061769e25f`이며 같은 HEAD로
  기록하지 않는다. 이전에 고정한 raw hash와 owner 구현·Prompt·입력·모델/runtime 동등성을
  검사한 default 6행만 재사용했다. 전체 manifest의 다른 slot 변경은 비교 의미에 섞지 않았다.

실제 **6 FIRST, 6 generation, schema repair 0, semantic revision 0**이다.
6개 모두 첫 출력의 schema/closed ID 검증을 통과했고 최종 출력이 첫 출력과 동일했다.
실제 입력 hash는 사전 고정 입력과 모두 일치하며, 현재 후보 instruction/schema를 다시
조립한 hash도 6개 실제 wire hash와 일치했다. temperature 옵션 미전송, seed 20260923,
think false, context 16384가 실제 wire에서 관측됐다.

### Case별 결과와 최초 손실

| Case | v31 default의 금지 effect | v32 첫 출력의 금지 effect | 관측 및 남은 실패 |
| --- | --- | --- | --- |
| CORE005 | 없음 | 빈 목록 | 원문의 새 작업 생성 금지를 계속 누락. 기존 frozen Goal/Work span에는 금지가 없지만 원문은 전달됐다. |
| CORE027 | 없음 | 빈 목록 | 원문·Work span·Goal·business concept에 일정 생성 금지가 모두 있는데도 CREATE를 누락. 입력의 단순 금지문 누락만으로 설명할 수 없음. |
| CORE056 | 없음 | SEND, UPDATE, DELETE | 비실행 지시의 효과 세 개를 회복했으나 CREATE 누락. 전체 비실행 의미 보존은 아직 실패. |
| CORE035 | 없음 | 빈 목록 | 사용자 Task 생성 요청을 금지하지 않는 control 유지. 업무 경계 재분해·메일 지시 안전성 전체 성공을 뜻하지 않음. |
| CORE059 | 없음 | 빈 목록 | 명시 SEND 요청을 금지하지 않는 control 유지. 승인·실제 발송은 미검증. |
| CORE002 | 없음 | 빈 목록 | READ Source 제외를 WRITE 금지로 확대하지 않는 control 유지. 실제 Source scope enforcement는 미검증. |

기존 기대 충족 control 회귀 0, 발명된 금지 0, 완전히 해결된 실패 Case 0이다.
누락 금지 결정은 baseline 6개 → candidate 3개이며, 그 세 개는 모두 CREATE다.
이는 Case 업무 성공률이나 실제 외부 WRITE 안전성의 완료 판정이 아니다.

`sparse → FORBIDDEN owner projection → 기존 Goal normalization`에서도 첫 출력의
effect/Work 귀속이 6개 모두 그대로 유지됐다. 원시 CREATE 누락을 validator가 채우지 않았다.
이 normalization probe는 빈 Source/Output responsibilities를 사용하는 component 확인이며
실제 Graph/Planning 실행이 아니다. Output consumer의 scoped 금지 연결은 앞서 직접 fake
test로만 검증했으며, 이번 6회 모델 실행에서 새로운 Output을 생성하거나 실행하지 않았다.

### CREATE 공통 실패의 책임과 확정할 수 없는 원인

확정 가능한 첫 divergence는 **전달된 owner 입력에서 첫 sparse structured output으로의
의미 판단**이다. 입력 원문이 wire에 존재하고, schema가 CREATE를 허용하며, 첫 출력부터
빠졌으므로 downstream normalizer/Output validator가 CREATE를 지운 것은 아니다.

Product-wide context는 유지했고 양식에 맞는 후보 책임 설명과 sparse schema만 변경했다.
따라서 Product-wide context가 원인이라고 단정할 비교 근거는 없다. Source/Resource-qualified
policy나 CREATE 코드 자체를 이해하지 못하는 모델 한계라고 결론내릴 근거도 없다.
별도 실제 MainGraph T2의 CORE005는 동일 Product Prompt/schema, default sampler와
think=false에서 CREATE FORBIDDEN을 첫 응답으로 생성했다
(`064-core005-main-graph-t2/calls.json`, call 3). T2는 Goal의 completion_conditions,
선택 ref UUID, 기준시각 등이 달라 동조건 재현 성공이나 v32 점수로 승계하지 않는다.
이 반례는 CREATE 판정 자체가 불가능한 것은 아니라는 근거다.

Goal/Work 중복 authority, effect의 추상 label, 공통 context가 의미 선택에 미치는 영향은
아직 가설이다. 027과 과거 062의 005는 Goal에도 금지가 있는 상태에서 실패했으므로
단순히 Goal에 금지를 더 써 주면 해결된다고 주장하지 않는다.

### 비용

| 경로 | 실제 호출 | 입력 tokens | 출력 tokens | provider latency 합 | usage 누락 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 재사용 v31 default | 6 | 11,622 | 546 | 21,632 ms | 0 |
| v32 sparse | 6 | 10,698 | 103 | 16,391 ms | 0 |

입력 -924 / 출력 -443 tokens, 기록된 latency 합 -5,241 ms다. FIRST 출력 분량 감소는
관측됐으나 단발이며 cache/warm-up을 통제한 속도 benchmark가 아니다. 특히 v32 첫005는
7,237ms였고 나머지는 1,425~2,988ms이므로 지연 감소를 일반화하지 않는다.
rerun-to-pass 0, Product/Prompt activation 0, Provider READ/WRITE/SEND 0이다.

### 기존 이력 확인과 다음 축 하나

- 금지 owner만의 thinking 비교는 기록에서 찾지 못했다. 다만 같은 설치 환경의 Source
  v12 generate+think는 최종 content 부재, v13 chat+think는 timeout으로 기각됐다.
  이 runtime 경로가 고쳐졌다는 새 근거 없이 같은 thinking 방식을 다음 기본 선택으로 반복하지 않는다.
- effect-prohibition만을 대상으로 안전 의미를 명시한 label/descriptor 비교도 확인되지 않았다.
  과거 060의 Resource metadata 보강은 Output owner 실험이며 14/20 → 12/20 회귀였다.
  이를 prohibition label 실험의 성패로 승계하지 않는다.
- Goal projection 제거는 043/044의 Output 경계, v21 등의 Goal/Output 후보에 있었다.
  effect-prohibition owner의 Goal 포함/제외만 고정 비교한 기록은 확인하지 못했다.

따라서 다음 하나를 고르면 **동일 sparse 표현에서 생성 Goal 입력만 제외하는 frozen-input
authority ablation**을 권한다. 원문·Work·effect 후보·sampler는 유지하며 Case 문구나
Few-shot·효과 label 규칙을 추가하지 않는다. Goal이 금지를 보존한 027도 실패했으므로
효과를 보장하는 수정안이 아니라 중복 해석 입력의 기여를 분리하는 진단이다.
금지가 원문에 있지만 앞선 해석에서 빠졌던005, 그대로 있는027, 포괄 금지056과 정상 control을
함께 봐야 한다. 별도 평가 입력 계약으로 범위를 선언하고 검증 전 Product에 반영하지 않는다.

현재 sparse 단독 복구안은 **REJECT**, 호출·출력 효율과 일부 효과 보존 아이디어는
비활성 후보 근거로 보존한다. 본 결과 분석 중 추가 모델 실행·코드 수정은 하지 않았다.
