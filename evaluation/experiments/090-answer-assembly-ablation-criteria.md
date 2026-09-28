# 090 — 등록 assembly 회귀의 제한된 wire 원인분리

## 가설과 범위

088의 실제 등록 compose 후보는 CORE005 2회에서 요청하지 않은 제목·메모를
선택했고, completed/reformulation/Calendar 6회는 의미를 보존했다. 084와 088의
FIRST 차이 중 공통 Product 문맥과 Prompt version 메타데이터의 영향을 각각
분리한다. 입력 중복 제거, 새 규칙, Few-shot, Source/값/Schema 변경은 하지 않는다.
084에도 입력은 두 번 존재했다. 기존 중복 제거 실패를 새로운 축으로 재시험하지 않는다.

이것은 **raw transport 진단**이다. 실제 등록 router/compiled Graph 연결의 신규
성공으로 보고하지 않는다. Product 공통 문맥 제거를 출시하거나 Product PromptRef를
과거 version으로 되돌리는 변경이 아니다. Product/Canonical/승인/Provider 계약은 불변이다.

## 역사 비교와 고정 8 FIRST

- 기준: `088-registered-answer-choice-t1/raw.json`, SHA256
  `41e086022a73ae24405e886e466052c0d2a78371258d82aa7b652f31d2788d0c`.
- 과거 version 근거: `084-answer-mode-first-t1/raw.json`, SHA256
  `3ce662090733ad1d7c8811a566f8f4541514198463212b69615540beca6a8a1b`.
- A: 실제 088 system의 `_PRODUCT_CONTEXT_INSTRUCTION` 문자열 **정확히 1개만**
  제거한다. 주변 개행과 입력 제목, 새 version, role, input, format의 순서·값,
  sampling/options를 그대로 둔다. CORE005 → completed → reformulation 순서 두 번: 6 FIRST.
- B: 실제 088 payload의 prompt JSON에서 `prompt_ref.prompt_version`만 실제 084의
  `v1`로 바꾼다. CORE005 두 번: 2 FIRST. 이것은 **미등록 metadata probe**이며
  실제 Product registry가 이 PromptRef를 resolve했다는 주장을 하지 않는다.
- 역사 비교는 독립 6개 baseline row를 재사용한다. CORE005 역사 2개는 A/B의 공통
  비교 대상이지 새로운 baseline 4회가 아니다. 새로운 matched baseline 실행은 없다.

현재 assembler로 역사 FIRST byte 재구성이 일치해야 시작한다. model digest/실제
Ollama metadata, 원본 및 변경 wire bytes, role/입력/schema 순서, 원문·snapshot·fixture·
Case/reference time/fault binding, source files, HEAD와 계획 hash를 봉인한다.
역사 SHA와 현재 SHA가 다른 점을 유지한다. 같은 모델 metadata는 과거의 모든 실행
조건이 인과적으로 동일했다는 증명이 아니다.

## 실행·판정 계약

qwen3.5:9b, think=false, seed20260923, num_ctx16384 및 나머지 **원본 wire options**.
새 temperature/presence 설정 없음. 직렬 1, FIRST8, repair0, retry0, 호출 timeout180초.
전체1200초 경과 시 **다음 전송부터 차단**하며 진행 중 호출을 강제 취소하지 않는다.
독점 plan claim으로 같은 고정 trial 재실행을 거절한다. 예외/timeout/중단도 원본 그대로
남기고 성공으로 대체하지 않는다. 실제 모델은 구현·fake gate 동결 후 root만 실행한다.

083/084와 동일 materializer/admission을 관측에 사용하되 INVALID/NO_DRAFT를 fallback으로
성공 처리하지 않는다. 의미는 자동 채점하지 않는다. mode 자체도 정답으로 강제하지 않는다.

- CORE005: 선택 Task의 상태·기한만 보존. 제목/메모 추가 선택과 과잉 정보는 회귀로 기록.
- completed: 완료 상태와 요청한 메모 보존, 없는 사실/실행 주장 금지.
- reformulation: 계정 발급·장비 수령 확인 내용을 정리하고 원문 문장 인용 금지 보존.

FIRST 선택 → deterministic materialized draft를 각각 검수한다. PASS/PARTIAL/FAIL,
회귀/과잉/누락, calls/tokens/latency와 실제 wire를 보고한다. 8회 결과를 전체 workflow,
Main Graph, terminal commit, Canonical92, 출시 성공률로 승계하지 않는다. 비교군 사이
효과가 없거나 회귀하면 해당 축을 기각하고 문구 patch를 추가하지 않는다. 좋아져도
원인 단정/자동 활성화 없이 등록 경계에서 별도 검증이 필요하다.

Provider READ/WRITE/SEND0, Graph0, 모델 준비/fake0, 원본 raw 수정0.
