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
