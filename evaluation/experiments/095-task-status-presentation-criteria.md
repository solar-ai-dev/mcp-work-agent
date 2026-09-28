# 095 — Provider enum의 LLM용 표현 대체 진단

094의 실제 Product Planning FIRST2는 필드 귀속을 보존했지만 `needsAction`을
`진행 중`으로 과잉 해석했다. FULL은 PARTIAL, PARTIAL 조회는 B의 예정일 미확인도
설명하지 않아 FAIL이다. 068의 `incomplete` 보조 fact 추가가 이미 실패했으므로
설명·규칙을 다시 추가하지 않는다. 이번 변수는 **보조 사실 추가가 아니라 enum 표기 대체**다.

## 가설·계약

Provider wire enum을 사실의 유일한 표현으로 모델에게 다시 해석시키는 경계를 분리한다.
기존 `_task_status(..., korean=False)`의 의미를 재사용해 `needsAction → incomplete`,
`completed → completed`로 표현한다. 이를 처리 상태·진행률로 확장하지 않는다.

- 같은 Run에서 봉인된 approved ref·handle·version·hash의 snapshot만 사용한다.
- 094의 합성 excerpt가 typed metadata의 기존 직렬화와 전체 일치해야 한다.
  임의 메일/본문 파싱이나 `status:` 문자열 탐지로 사실을 고치지 않는다.
- 재직렬화는 status 값만 변경한다. 제목·메모 속 같은 문자열, 날짜·identity·원문·
  RequestIntent/Source/조건·outline·조회 상태는 모두 불변이다.
- 원 Evidence/snapshot/State는 변경하지 않는다. 새로운 evaluation input view이며,
  normalized text/segment/hash가 같다는 주장을 하지 않는다.05/15의 비활성 경계를 따른다.
- 양쪽 wire 입력 복사본에 동일 view만 적용한다. Prompt 문구·ROLE·Schema 값/순서·
  sampling/model은094 그대로다. Product Registry가 새 view를 resolve한 실행이 아닌
  미등록 transport ablation이다. 기존 PromptRef는 역사 출처로만 보존한다.

## 실행 전 고정

- 기준은094 native full/partial 각1회 raw를 그대로 재사용한다. 기준 SHA `befbb77a`,
  raw SHA256 `c105a18762ceda2b070dea3b82995e502d4aec447a3f3376a1940c11f4676f14`.
- 신규는 FULL→PARTIAL 각1 FIRST, **총2회**. 실패 Trial 대체·repair·retry0, concurrency1.
  호출당180초, 전체420초 전 다음 dispatch 차단. transport/model/seal 이상 시 다음 실행 중단.
- completed는 wire가 완전히 같은 no-op이므로 중복 모델 호출하지 않는다. 직접 검사의
  보존 확인만 하고, 새 completed 모델 의미 검증이나 무회귀 입증으로 계산하지 않는다.
- qwen3.5:9b exact digest/Ollama metadata/ctx16384/think=false/seed20260923,
  temperature/presence 미전송을 유지한다. 실행 전후 HEAD/source/history/model/wire 봉인.
- 본문/상태를 변조한 snapshot, 잘못된 hash·version·handle·ref, legacy 결속 부재,
  비Task, 승인 밖 Evidence, 제목·메모의 가짜 enum을 직접 검사한 뒤 실제 호출한다.
- 합성 fixture·reference time/fault와094의 입력을 유지한다. Dataset/Gold 변경0.

## 판정과 다음 선택

094와 같은 의미 기준으로 판정한다. FULL은 A 미완료와 B의 date-only 예정일을 구분하고,
PARTIAL은 A의 확인된 상태와 B 예정일 미확인을 전달해야 한다. A의 기한을 B 답변으로
전이하거나, 착수·진행률을 발명하거나, 미확인을 숨기면 해결로 보지 않는다.
상태 표현만 맞아도 부분조회 누락이 남으면 전체 PASS로 올리지 않는다.

원문→view→FIRST의 최초 차이, PASS/PARTIAL/FAIL, 범위·누락·불필요 사실,
calls/tokens/latency를 기록한다. 구조 VALID를 의미 PASS로 대체하지 않는다.
개선되면 표현과 그 전달 계약만 다음 compiled 경계에서 검토한다. 개선되지 않으면
동일 enum 설명/보조 fact를 반복하지 않고 참조 렌더링·업무별 coverage의 책임을 재검토한다.

실제 Provider READ/WRITE/SEND0, Graph0, Product source/활성 Prompt/Approval 변경0.
이2개 입력은 Canonical92 성적·반복 안정성·업무 종단 성공이 아니다.
상세 raw는 ignored `evaluation/results/`, 검증된 요약은 별도 result 문서에 남긴다.
