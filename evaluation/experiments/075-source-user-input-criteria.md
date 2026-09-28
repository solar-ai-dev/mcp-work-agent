# 075 — SYSTEM 입력 사본 제거, USER authority 위치 대조

074는 올바른 참고 해석을 추가했어도049의 명시 Source가 전부 사라졌다.
새 자연어 규칙보다 현재 모델이 입력을 받는 envelope 위치를 검사한다.
과거v22는 USER input을 제거해 SYSTEM-only로 만들었고 회귀로 기각됐다.
이번은 그 반대인 USER-only 대조다. 같은 기각을 새 방법으로 포장하지 않으며,
중복 감소와 role 위치의 인과를 완전히 분리하는 실험이라고 하지 않는다.

## 사전 고정

- Core017/049/005, 각 arm FIRST1. 신규총6, concurrency1, timeout180초, retry/repair0.
- `plain_user_only`: 현재 재구성된 역사v42 실제 Source wire에서 SYSTEM input 사본만 제거.
- `interpretation_user_only`: frozen074 Source wire에서 같은 위치만 제거.
- 순서017 plain→interpretation,049 interpretation→plain,005 plain→interpretation.
  원 baseline/074의 실패 Trial을 대체하지 않는다. 두 arm을 임의로 합쳐 best-of 점수 금지.
- canonical request·selected·clock·Goal·Work·catalog·USER schema/ref·format·sampling
  그대로. SYSTEM role instruction/공통지시는 그대로이며 정확한 Input JSON suffix와
  해당 제목만 제거한다. 원문을 자르거나 의미를 교정하지 않는다.
- 074 actual raw hash
  `94c3fadd968a8dd152ac0d9e605af1b8ccd47f44cab62365d39679b322ee61d7`.
  plan/current reconstruction으로 model·Source Prompt/Schema·입력·validator 동일성 검사.
- qwen3.5:9b 기존digest/Ollama0.34.0/temp0.05/seed20260923/ctx16384/think=false.
  final response만 저장, 숨겨진 추론 미사용. generation 중 편집/테스트/다른모델0.
- transport/timeout/미완료/모델drift는 남은 미실행 표시. 의미/Schema실패는 다음고정Case.

## 평가·다음 선택

074의 Source-only 기준을 그대로 사용한다. baseline3 =1PASS/2PARTIAL,
074참고문추가3 =2PASS/1FAIL. 기준SHA·신규/재사용·같은3건을 분리한다.
원 Source FIRST→strict validator→source-only merge 보존을 확인한다.
생성 Output을 기존 Source로 요구하는 과잉, 명시 Source누락, scope/Work손실 및
005성공 회귀를 보고한다. exact Resource개수·Tool순서·전체업무성공을 강제하지 않는다.

효과가 없으면 role/locus 문구patch나전체92로 확대하지 않는다. 개선arm이 있어도
같은3건 단발을 안정성이라하지 않으며 no-source/update/복수Work반례와다른기존성공으로
확대할 근거로만 사용한다. costs는각arm분리, 참고문arm은072해석비용도별도포함한다.
새ProductState/Promptactivation/Graph변경0, Provider/Approval/WRITE0.
이번진단은 LoRA효과나Production마이그레이션/전체LangGraph성공을증명하지않는다.
