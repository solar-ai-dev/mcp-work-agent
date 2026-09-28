# 066 v46 — 지원 고정 모델 4B/9B Source FIRST 진단 / 사전 기준

## 다음 축의 근거

v45까지 Source 입력·catalog·표현·Prompt·Few-shot·sampler 후보에서 필요한 Task/메일
누락 또는 기존 Draft 과선택이 반복됐다. 일부 Case 개선을 다른 실패와 교환했으므로
같은 projection/문구 후보를 다시 만들지 않는다. 현재 T3에서도 Goal의 실행값 오염과
Output의 미요청 WRITE는 조립 손실이 아닌 실제 FIRST부터 존재했다.

이것을 곧바로 모델 한계나 학습 필요성으로 결론내리지 않는다. Canonical13 §17.1과
#296의 학습 없는 지원 모델 구성, #303의 model-native runtime 확인 범위에서 **이미
설치된 4B와 같은 frozen Source 입력**을 비교한다. 기존 기록에서 이 exact 입력의 4B
비교는 확인하지 못했다. 4B가 더 좋을 것이라고 예상하거나 더 작은 모델의 실패를 9B
한계 증거로 쓰지 않는다. 목표는 이 계약에서 artifact별 실패 양상이 다른지 확인하는 것이다.

## 고정 비교

- baseline: v42 default9B의 CORE009/049/059 Source FIRST 각1회 재사용.
  bytes hash `f5b40bd0d4e36e0f7d9138d00d9d0bdd45cbebc5cd954a110ced1d3a50c6ee52`.
  현재 assembler/Schema/validator 전체 wire 재구성 일치 검사를 통과한 원 결과만 사용.
  과거와 현재 SHA 차이를 plan에 기록한다. v45 metadata ablation은 적용하지 않는다.
- candidate: 같은 원 payload에서 `model`만 `qwen3.5:4b`로 변경.
  역할·원문·전체 catalog·Work/Goal·Schema·Registry·모델 선택 외 options 불변.
- 모델 digest: 9B `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`,
  4B `2a654d98e6fba55d452b7043684e9b57a947e393bbffa62485a7aac05ee4eefd`.
  둘 다 Q4_K_M/qwen35, 서로 다른 weights와 크기이므로 순수 parameter-count 효과가 아니다.
- Ollama0.34.0, temp0.05/seed20260923/ctx16384/think=false/non-stream /api/generate.
  show defaults: presence1.5/temp1/top_k20/top_p0.95. options의 Source temp가 default를 대체.
  actual show/template/renderer 관측 hash를 계획에 결속하고 drift 시 실행하지 않는다.
- 4B FIRST **신규3회**, 각 Case1회, repair/retry/rerun0, 직렬1. timeout은 기존180초.
  전체9B Graph 모델 전환이나 실패 시 fallback이 아니라 독립 frozen-owner 진단이다.
- Dataset/Fixture/Case/reference-time/fault binding은 원 v42 입력 그대로다.
  Holdout/Stress 튜닝·Provider·승인·제품 설정/Prompt/activation·모델 다운로드/학습0.

## Runtime 사전 확인

무추론 `_debug_render_only=true`의 합성 sentinel에서 4B system/user/assistant role
boundary와 think=false 종료 구간을 확인했다. response는 빈 값이며 debug 응답의
done=false를 미완료 generation으로 해석하지 않는다. token generation0이다.
이 검사는 모델을 준비/load할 수 있으므로 새 호출 지연을 cold9B와 인과 비교하지 않는다.
실제 진단은 done/done_reason, 실제 input/output token·duration·wall·usage 누락을 기록한다.

## 고정 의미 기준·중단 조건

기존 v42/v45 기준과 동일하게 user request/Canonical semantics로 채점한다. Resource
개수/Tool 순서 일치가 업무 정답은 아니다. parent/container의 정상 보조 조회를 기계적으로
FAIL 처리하지 않으며, 요청 Source 누락·Source/Output 혼동·무관한 필수 조회는 별도 기록한다.

| Core | 지켜야 할 의미 | baseline |
| --- | --- | --- |
| 009 | 진행 상황 답변에 필요한 메일과 Task 근거 모두 보존 | FAIL: Task 누락 |
| 049 | 명시된 메일·Task·Calendar 사실 접근 보존. 생성할 Draft를 기존 필수 Source로 혼동하지 않음 | PARTIAL: 필수 사실은 있으나 기존 Draft 과선정 |
| 059 | 회신 대상 메일의 내용/이력 보존. 새 회신을 기존 Draft snapshot 의존으로 바꾸지 않음 | PASS |

원 raw/FIRST/schema/validator 결과를 모두 남긴다. 구조 PASS와 의미 판정을 분리한다.
개선이 없어도 실패 Trial을 교체하지 않고 92개로 확대하지 않는다. 기존 성공 회귀나
필수 Source 손실이 있으면 4B를 안정화 해법으로 채택하지 않는다. 3/3 좋아져도 반복
안정성·Output/금지 owner·실제 RU→Graph·업무 성공·지원모델 Release Gate는 미검증이다.

## 자원 제한

검토 시 RAM 여유19.68/31.71GiB, GPU0/8188MiB·52°C였다. 4B 사전 렌더 후
실제 실행 직전/중간/종료 snapshot을 따로 기록한다. 다른 서버를 재시작하거나 사용자
process를 종료하지 않는다. generation 중 편집/pytest/다른 모델0, 새 clone/대형 download0.

## 실행 전 직접 gate

신규11개 + 재사용 실행기/원 catalog projection 회귀21개 = **32 PASS / 1.03s**.
model 키만 변경, full catalog 보존, metadata 읽기의 generation0, 기존 렌더 관측 결속,
실제응답 모델 mismatch를 성공으로 채점하지 않음, hash/모델/입력 drift 차단, exclusive
trial claim을 검사했다. Ruff 및 두 실행 모듈 mypy PASS. Product 의미 성공 검사는 아니다.
