# 091 — 조회용 파생 constraint의 답변 입력 중복 분리

## 가설·변수

088의 답변은 상태·기한만 요청했는데 Source의 전체 필드를 골랐다. 090 공통 문맥 제거는
lookup을 고치면서 재작성 요청을 깨뜨렸으므로 기각했다. 새 규칙·Few-shot·문구 patch를
추가하지 않고, 조회 목적의 의미가 답변 요구로 중복 노출되는 표현만 비교한다.

원본 compose 입력은 기존 Product input contract로 먼저 검증한다. 그 뒤 평가 전용
projection에서 기존 source_reads로 `derive_source_information_constraints`가 **정확히**
재구성하는 USER_REQUIREMENT.required_information 항목만 생략한다. 값, work_unit_ids,
필드 전체가 같아야 한다. provenance/사용자 정정이 붙은 값이나 별도 constraint는 보존한다.
원문·Goal·원래 Source·Output·기타 constraint·WorkUnit·Evidence·outline·coverage는 변경0.

이는 RequestIntentV3 자체의 변경·재검증이 아니다. 별도 evaluation input version과
원본→projection 등가 검증으로 닫는다. 결과는 original input/snapshot의 동일 fact catalog,
동일 Answer validator/materializer로 검증한다. 원하는 field/정답개수는 강제하지 않는다.

## 사전 고정 비교

- 기준: 088 실제 raw의 Task 세 입력×두 반복=역사6 FIRST. 4 PASS/0 PARTIAL/2 FAIL.
- 신규: 같은 순서 lookup→완료·메모→메모 재작성, 두 반복=6 FIRST.
- 입력·Snapshot·Canonical/fixture hash·reference time·fault binding은 기존 근거를 재사용한다.
  두 합성 control을 실제 upstream Run이나 별도 Canonical Case로 표시하지 않는다.
- wire에서는 입력 JSON만 양쪽 위치에서 동일하게 바꾼다. ROLE, 공통 문맥, 입력 제목,
  PromptRef metadata, Schema의 값/property 순서, model/options는088 그대로다.
  PromptRef 문자열을 통제한 미등록 wire 진단이며 해당 Product Ref가 새 입력을 resolve한
  등록 실행이라고 주장하지 않는다. 새 입력 contract/version은 실험 plan에 명시한다.
- model qwen3.5:9b/digest와 Ollama metadata 일치, ctx16384/think=false/seed20260923.
  temperature/presence 새 override 없음. concurrency1/FIRST6/repair0/retry0.
- 호출180초, 전체1200초 이후 다음 dispatch 차단. exclusive claim과 HEAD/source/history/
  ordered wire/model 봉인을 시작·종료에 확인한다. 실패/timeout도 보존하고 재실행하지 않는다.

## 판정·다음 선택

본문 원문 인용 금지, 완료 사실, 상태·기한만이라는 범위를 기준군과 동일하게 판정한다.
mode 자체는 정답이 아니다. structural VALID와 의미 PASS/PARTIAL/FAIL을 구분하며 자동
meaning override 없이 FIRST와 materialized answer를 둘 다 검수한다.
Source/기타 constraint가 실제 보존됐는지 직접 반례검사 후 모델을 실행한다.

개선과 무회귀가 함께 확인되면 같은 projection을 명시적으로 등록한 실제 Planning
router/compiled 경계로 검증을 확장한다. 효과가 없으면 중복 삭제를 더 넓히지 않고
현재 output mode 선택/답변 범위 표현의 실패군을 재검토한다. Main/92로 바로 승계하지 않는다.

Provider/Graph0, Product/Prompt activation/Approval/Execution 변경0. 상세 입력/응답은
evaluation/results의 ignored artifact로, 검증된 결론은 versioned 실험 문서에 보존한다.
