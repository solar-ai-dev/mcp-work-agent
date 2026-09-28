# 064 v33 — 생성 Goal 입력만 제외하는 금지 owner 진단

## 가설과 고정 경계

v32는 CREATE 금지 누락을 해결하지 못했다. sparse 표현에서 SEND/UPDATE/DELETE 일부가
회복됐지만 원문에서 첫 owner 출력으로의 의미 판단은 불안정하다. 이번에는 생성 Goal이
원문과 중복된 의미 authority로 작용하는지 **입력 root field 하나의 제거**로 비교한다.
Goal 제거가 성공할 것이라고 전제하지 않는다. 027은 기존 Goal에도 금지가 있었고,
별도 MainGraph T2에서는 Goal에 금지가 보존된 상태에서 CREATE 판단에 성공한 반례도 있다.

- 기준: v32 실제 동일 6개 frozen input/결과. ID 순서 005/027/056/035/059/002 유지.
- 유일한 모델 입력 변경: `goal_candidate` root field 제거.
- 원문, Work 정의/provenance, effect 후보, selected refs, 기준시각은 그대로 유지.
- v32 Prompt 본문과 source hash, Product-wide instruction, OutputSchema, semantic owner,
  FIRST 1회, default sampler(None → 실제 모델 기본 1), seed 20260923, think false 유지.
- Prompt의 기존 Goal 설명 문장도 바꾸지 않는다. 이번 평가 입력에는 그 필드가 없음을
  별도 입력 계약에 명시하며, Prompt 문구 조정의 효과를 섞지 않는다.
- Schema/Gold/규칙/Few-shot/Work 재분해/Resource-qualified policy를 추가하지 않는다.

Candidate ID: `goal-absent-prohibitions-v33`.
평가 입력 계약: `evaluation-goal-absent-v33`.
Prompt 본문 version/hash는 v32와 같고 PromptRef의 input schema version만 후보 계약으로 구분한다.
wire PromptRef의 body version/hash는 그대로이며 실제 JSON input과 관측 hash가 달라진다.

## Product loader와 정규화 경계

Product 입력 계약은 여전히 Goal을 요구하며 변경하거나 무력화하지 않는다.
원래 frozen 전체 입력을 Product assembler로 검증한 뒤, evaluation projection이
`Allowed current-Run input projection`의 exact JSON root에서 Goal 필드만 제거한다.
Prompt 본문·Product-wide 문맥·repair failure instruction은 그대로 유지한다.
모델에 보내는 wire input과 system JSON projection 둘 다 Goal이 없으며 FIRST와 repair에
동일하게 적용한다. 입력이 고정 원문에서 달라지거나 새로운 필드가 섞이면 dispatch 전에 거절한다.

원래 Goal은 `normalization_goal_candidate`라는 **평가 기록의 외부 context**에만 보존한다.
모델 입력에 이 외부 context를 보내지 않는다. 정규화 probe는 원래 Goal을 복원해 원 입력
hash까지 확인한 뒤 같은 Product normalizer를 사용한다. Goal 원문을 새로 만들거나 수정하지 않는다.
schema-valid한 빈 금지 목록을 원문이나 Gold를 보고 자동으로 채우지 않는다.

## Baseline 재사용 및 사전 등록

- baseline raw: `evaluation/results/064-prohibition-sparse-v32-t1/raw.json`.
- raw bytes hash: `358ad42822b4b4c020b75d7df26db4872d9a155f2727df12e4dc8975b058f77d`.
- v32의 실제 6행만 재사용한다. HEAD 차이를 숨기거나 새 baseline 실행이라고 기록하지 않는다.
- 관련 owner 구현·v31/v32 harness·모델 digest/parameters·runtime·PromptRef·schema·frozen
  input·actual system/wire option 동등성을 재확인한다. global manifest가 다른 owner 작업으로
  달라져도 금지 owner의 input slot/전역 forbidden field 규칙과 actual assembled input이
  같아야 한다. 관련 owner 자체 변경이면 재사용하지 않고 실행을 거절한다.
- 새 plan에 원래 input hash와 실제 Goal 없는 input hash, 외부 normalization context,
  후보 input contract/hash, v32 module hash, v33 module hash를 별도로 기록한다.

후보는 6 FIRST + 각 최대 1 schema repair = **신규 generation 최대 12회**다.
semantic revision/transport retry/rerun-to-pass 0. FIRST/repair/validator/normalization 결과,
actual wire 옵션/input/hash, calls/tokens/latency/usage 누락을 분리 보존한다.
실패 Trial을 교체하거나 Gold를 바꾸지 않는다. Provider와 Graph 실행은 없다.

## 실행

v32 CLI·bounded 실행·repair guard·관측을 작은 v33 wrapper에서 재사용한다.
Product·v31/v32 모듈 파일을 수정하지 않는다. 실행 전 현재 코드/HEAD를 동결하고
다른 Ollama Trial과 겹치지 않게 한다.

```powershell
.venv/Scripts/python.exe -m scripts.evaluate_goal_absent_prohibitions --result-dir evaluation/results/064-prohibition-goal-absent-v33-t1
```

위 명령은 model catalog/show 확인과 사전계획 생성만 한다(generation 0).
출력된 normalized plan SHA를 그대로 사용한다.

```powershell
.venv/Scripts/python.exe -m scripts.evaluate_goal_absent_prohibitions --result-dir evaluation/results/064-prohibition-goal-absent-v33-t1 --execute-plan evaluation/results/064-prohibition-goal-absent-v33-t1/preregistered-plan.json --expected-plan-sha256 <출력된 SHA>
```

## 준비 검증과 판정 범위

새 v33 직접 테스트 15개 + v32/v31/관측 회귀 52개 = **67 PASS**.
원래 input 복원 hash, 동일 Prompt 본문/Schema, Product loader의 Goal 필수 계약 유지,
FIRST/repair 실제 wire 양쪽에서 Goal 제외, 외부 normalization context 보존,
새 필드·Goal 재주입 거절, bounded repair를 확인했다. synthetic transport이며 모델 평가는 아니다.

기존 aggregate effect 기대와 closed Work binding 검증의 한계를 그대로 유지한다.
owner 개선을 업무 전체 성공/Production 채택으로 보고하지 않는다. 구조·의미·normalization
결과를 구분하고 금지 누락/발명·기존 control 회귀·비용을 함께 비교한다.
준비 단계 실제 모델 호출·Provider 호출·Product 변경은 0이다.

## 실제 실행 결과 — 2026-09-28

**owner 기대 충족은 v32 3/6 → v33 4/6으로 개선됐다.** CORE056의 포괄적 비실행
지시에서 빠졌던 CREATE가 회복됐고, 기존 성공 control 3개는 유지됐다.
CORE005/027의 CREATE 금지는 여전히 누락된다. 따라서 Goal 제거가 전체 원인을 해결했거나
금지 owner가 반복 안정화됐다고 결론내리지 않는다. 평가 후보는 보존하되 Production에 반영하지 않는다.

### 실행·원시 근거

- 실행 HEAD: `eb8f99340b6b39d916ef2a86a6e903454369f37f`.
- raw: `evaluation/results/064-prohibition-goal-absent-v33-t1/raw.json`.
- raw bytes SHA-256: `35af3d66e9c68654ddc5cbacd6ac75e34a5bb006cd0aca74ad429f6e8c73d3dd`.
- 사전계획 bytes SHA-256: `327516f5adb2ab0ede581eda7b838263a0feb1dc51b3e0fc887a0b8cdde16fa6`.
- 후보 module hash: `3c1702ad898ec27265cae3a5555c11ea7864e44b6d79baf77d2f29ec09f94b8a`.
- 입력 계약 hash: `07b8ffdcb94172cac197e8245a034fb6fff2c2ed893f37d2ff46a67aaa417437`.
- v32와 동일한 Prompt body hash:
  `b380e0f384c8a017e5fb7837754f3fe994d1b17cfc588ca23f96656994b9337c`.
- 동일 모델 digest:
  `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`.

실제 **FIRST 6회 / generation 6회 / repair 0회 / semantic revision 0회**다.
구조 검증은 6/6이며, 모든 최종 출력과 normalization 결과는 FIRST에서 생성된 금지
effect/Work 목록을 그대로 보존했다. 의미 오답을 validator로 보정하지 않았다.

6쌍의 실제 transport input을 비교하면 v32 input에서 `goal_candidate` root field만
제거한 값과 정확히 같다. Work/provenance·원문·선택 Resource·기준시각·effect 후보는
바뀌지 않았고 OutputSchema hash도 6쌍 모두 같다. 실제 system hash는 별도 평가 projection으로
다시 조립한 값과 일치한다. 외부 normalization context로 복원한 원래 input hash도 6/6 일치했다.
따라서 이번 입력 제거를 Dataset/원문 훼손이나 Goal 데이터 삭제로 취급하지 않는다.

actual wire는 temperature 옵션 미전송, seed 20260923, context 16384, think false다.
모델 parameters의 기본 temperature 1 / top_k 20 / top_p 0.95 / presence_penalty 1.5를
그대로 사용했고 sampler 변경은 없다. Prompt body에는 이전 Goal 설명 문장이 그대로
남아 있으며, 그 문구 수정 효과를 이번 결과에 섞지 않았다.

### 구체 결과

| Case | v32 금지 목록 | v33 첫 출력 | 의미 판정 |
| --- | --- | --- | --- |
| CORE005 | 빈 목록 | 빈 목록 | 새 Task 생성 금지 → CREATE 결속 누락 유지. |
| CORE027 | 빈 목록 | 빈 목록 | Event 생성 금지 → CREATE 결속 누락 유지. |
| CORE056 | SEND/UPDATE/DELETE | CREATE/UPDATE/SEND/DELETE | 전체 비실행 의미를 이 Trial의 첫 출력에서 보존. 기존 Work ID에 정상 결속됨. |
| CORE035 | 빈 목록 | 빈 목록 | 사용자 Task 생성 요청을 금지하지 않는 control 유지. |
| CORE059 | 빈 목록 | 빈 목록 | 명시 SEND 요청을 금지로 바꾸지 않는 control 유지. 승인은 별도. |
| CORE002 | 빈 목록 | 빈 목록 | READ Source 배제를 WRITE 금지로 바꾸지 않는 control 유지. |

새로 완전히 충족한 owner Case 1개(056), 기존 성공 회귀 0, 발명된 금지 0이다.
누락 금지 결정은 3개 → 2개다. 이 수치는 Canonical 92 전체나 실제 업무 성공률이 아니다.
정규화 component 연결은 보존됐지만 이 실행에는 Source/Tool Route/Planning/Provider가 없다.

### 남은 failure family와 인과 해석

1. **포괄적 비실행 → 복수 효과 금지:** 056은 이번 입력 authority 비교에서 개선됐다.
   같은 sparse Schema/Prompt/runtime을 유지했으므로 Goal 제거가 유력한 비교 근거이지만,
   단일 Trial이어서 반복 신뢰성이나 모든 비실행 요청에 대한 인과 법칙은 아니다.
2. **특정 업무 Resource 생성 금지 → CREATE:** 005/027은 실제 원문을 입력받은
   effect-prohibition owner의 첫 출력에서 계속 누락한다. 이후 normalization은 빈 목록을
   충실히 전달했으므로 최초 실패를 downstream consumer에 돌리지 않는다.
3. **Work/input 귀속과 분리할 사항:** 005의 frozen Work span에는 금지문이 없지만
   027의 Work span에는 금지문이 포함돼 있다. 따라서 Work span 밖에 있는 조건만의 문제로
   공통 원인을 설명할 수 없다. Source exclusion control002는 정상이며, Source READ 금지와
   WRITE 금지 혼동을 두 잔여 실패의 확정 원인으로 분류하지 않는다.

CREATE label 자체가 표현 불가능하거나 Resource-qualified policy가 원인이라고 단정하지 않는다.
별도 MainGraph T2 CORE005는 **Goal이 있는 상태**에서도 같은 Product Prompt/schema/default
sampler에서 CREATE FORBIDDEN을 첫 출력으로 생성했다. T2의 completion_conditions에는
새 작업 금지가 있으며 선택 ref UUID·기준시각·Goal 내용도 다르다
(`064-core005-main-graph-t2/calls.json`, call 3).
이는 Goal 존재가 항상 오류를 일으킨다는 설명의 반례이지만, 어느 입력 차이가 결과를 바꿨는지를
분리한 실험은 아니다. T2 성공을 v33의 동일 조건 성공으로 승계하지 않는다.

따라서 현재 확정 책임은 잔여 두 Case의 **원문 제약 → 첫 명시금지 선택** 경계다.
Goal 간섭·effect 개념 결속·Work 귀속 중 어떤 요인이 공통 원인인지 아직 확정하지 않았다.
이 보고 단계에서는 새 후보나 Case별 Prompt/Rule을 만들지 않았다.

### 비용·채택 범위

| 경로 | 실제 호출 | 입력 tokens | 출력 tokens | provider latency 합 | usage 누락 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 재사용 v32 | 6 | 10,698 | 103 | 16,391 ms | 0 |
| v33 | 6 | 8,328 | 120 | 15,051 ms | 0 |

입력 -2,370 / 출력 +17 tokens, 기록된 latency 합 -1,340ms다. Goal 제거에 따른 입력 축소는
확인되지만 warm-up/cache를 통제한 속도 비교가 아니므로 지연 개선을 일반화하지 않는다.
v33 첫005의 latency는 6,651ms이고 나머지는 1,220~3,325ms였다.

**판단: 입력 authority 절제는 개선 근거로 보존, Production 채택은 미확정.**
미해결 005/027, 반복 Trial, multi-work 의미 귀속, 실제 connected workflow 이후는 미검증이다.
rerun-to-pass 0, Provider READ/WRITE/SEND 0, Product/Prompt activation 0.
본 결과 분석 중 추가 모델 호출·코드 변경은 0이다.
