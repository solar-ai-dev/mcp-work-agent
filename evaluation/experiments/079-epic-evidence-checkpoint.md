# #286 — 074~079 Source 안정화 근거 정리

전체 LangGraph 안정화는 **미완료**다. Product는 유지하며, 실패 후보를 활성화하거나
부분 Source 점수를 RU→Tool Route/업무 성공률로 승계하지 않았다.

## 어떤 문제가 남았는가

핵심은 모델의 Source FIRST에서 **이미 존재하는 근거와 새로 만들 결과의 대상**을
섞는 오류다. 049는 기존 Atlas 자료를 확인한 후 새 인계 Task를 만드는 요청인데,
076은 새 인계 Task의 현재 사실을,079는 기존 인계 Task의 사실을 요구했다.
077에서 Goal 파생 조건만 제거하면 정보 표현은 나아져도 조회 범위를 SINGULAR로
좁혔다. 유효한 원 출력은 validator/merge가 그대로 유지하므로 후처리 코드가 의미를
새로 바꿨다는 근거는 없다. Query/Provider 이후 실패는 이번 범위에서 실행하지 않았다.

## 후보별 판단 — 서로 다른 분모를 합산하지 않음

| 후보 | 고정 비교 결과 | 판단·재시도 조건 |
| --- | --- | --- |
| 074 기존 입력+최종 자연어 해석 | Source3건:1P/2PART→2P/1F.049는 전부 NOT_REQUIRED | REJECT. 비권위 해석 추가가 판단을 안정화하지 않음. |
| 075 SYSTEM 중복 입력 제거 | plain1P/1PART/1F;해석 추가 arm1P/2PART | REJECT.049누락/017불필요Draft 간 실패 교환. |
| 076 Resource 하나씩 판정 | 부분 Core4/6→5/6,합성1/2→2/2 | 부분 개선 보존. membership8/8이나049 대상 오류. 전체 Source나 N-call 배포 채택 아님. |
| 077 Goal 파생 조건 제거 | 같은4개3P/1F→3P/1F | REJECT. 대상 오류가 SINGULAR 범위 축소로 이동. |
| 078 focal+native reasoning | 첫1개 empty final,뒤3개 미실행 | REJECT(호환성). 의미 성공률 측정 불가. |
| 079 같은 reasoning에서 format만 생략 | final3/3,strict2/3,계약+의미2/3→1/3,뒤1개 미실행 | REJECT.049대상 오류 유지,017Schema회귀,지연합22.61배. |

074~077의 세부 raw·hash·기준 SHA는 각 보고서에 있다. 078/079는 원래 실패를
교체하는 재실행이 아니라 사전 고정한 독립변수 대조다. 구조 실패 후 미실행은 분모에서
분리했고, 의미가 틀린 Trial을 숨기거나 성공할 때까지 반복하지 않았다.

## 자원과 검증

- 구간 시작 `2f4964e45a7b966fd87ce4c3bd9137ed3499cbd8`.
- 신규 실제9B calls **25**,input93,729/output11,725,reported latency합469,373ms.
  이는 실험 비용 합계이지 하나의 workflow 비용/성공률이 아니다. 추론모드 output은
  provider 전체 생성량이며 hidden 내용은 저장하지 않았다. usage 누락0.
- 동시 모델 생성1, 생성 중 코드편집/pytest0, Provider/Approval/WRITE/repair/retry0.
  RTX4060Laptop8GB에서 모델 상주 약6.4GB. 더 무거운 학습/다운로드를 동시에 실행하지 않았다.
- 직접 관련 harness 회귀 **118 PASS**, scoped Ruff/mypy PASS.
- 넓힌 architecture gate는 기존과 같은 **20 PASS/3 FAIL**. 세 실패 범주는 Agent
  operation/mirror,peer-test import,명명 규약이다. 이번에 추가한 두 peer import는
  공통 fixture를 `tests/support/source_dependency_wire.py`로 이관해 제거했다.
  나머지 기존 위반을 무관한 대량 리팩터링이나 assertion 완화로 숨기지 않았다.
- Product source/활성 Prompt/Runtime/Graph 변경0. 이전073 Task collection scope 수정 유지.
  새 Canonical92 모델 평가/전체pytest/Live Provider 실행0.

## 다음 선택에 필요한 근거

같은 입력에서 규칙/Schema 문구를 조금씩 바꿔 반복하거나 Resource N-call을 바로
Production에 적용하지 않는다. v43의 membership→details 분리도 이미 같은 후단
대상 오류를 남겼으므로 이를 새 구조인 것처럼 반복하지 않는다.

학습 없이 해결되지 않는 잔여 오류에 대한 #296의 독립 adaptation 비교는 유효한 다음
축이지만, 현재 결과만으로 LoRA가 필요하거나 효과가 있다고 결론내리지는 않는다.
read-only 준비 감사 결과 기본 Ollama 저장소에는9B/4B Q4_K_M만 있으며, 기본HF cache에서
Qwen trainable weights,현재 venv에서Torch/Transformers/PEFT,repo에서독립train/dev
manifest를 확인하지 못했다. 전체디스크 부재를 주장하지 않는다. 기존Canonical raw와
평가에 사용한 합성 control은 독립 학습/검증 데이터로 재사용하면 안 된다.

새 학습 축은 Canonical과 분리된 train/dev,같은base전후검증,8GB GPU에 맞는 메모리
예산부터 고정해야 한다. #304의 양자화 배포 비교는 현재 이슈의 선행 안정화 gate가
있으므로 준비됐다고 가정해 대용량 모델을 내려받거나 배포 후보로 승격하지 않았다.
실제 훈련·고정밀 모델 검증은0이며 사용자의 새 권한 결정이 필요하다고 단정하지 않는다.

원격에는 비민감 결론·runner·criteria·tests를 남기며, detailed raw는 기존
`evaluation/results/` 로컬 ignore 영역에 보존한다. 해당 raw가 필요한 외부 리뷰에는
별도 안전 전달이 필요하다. 이번 범위의 기각은 Epic 완료나 중단 선언이 아니다.
