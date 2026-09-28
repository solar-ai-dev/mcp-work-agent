# 068 — 검증된 Task completion fact의 ANSWER 입력 전달 후보

## 근거와 변경 축

064/067의 실제 MainGraph compose FIRST는 raw `needsAction`을 전달받고도 진행 중이라고
답했다. 이 enum은 완료 여부이며 착수/진행률 사실이 아니다. 기존 deterministic formatter와
Resource detail projection의 미완료 의미를 사용하고 새 업무 판단·문구 교정 규칙을 만들지 않는다.

비활성 개발 후보는 `task_completion_facts`만 추가한다. approved Evidence의 same-Run
snapshot에서 기존 hash/version/handle resolver로 검증된 `needsAction→incomplete`,
`completed→completed`를 ref와 함께 전달한다. 기존 원문/intent/Evidence/outline은 불변이다.
Prompt 본문·출력 Schema·Node·추가 LLM 호출·Product runtime 변경0. 별도 evaluation PromptRef와
input contract가 이 optional field만 허용한다. Product release registry/activation은 그대로다.

- fact 필드: evidence_ref, resource_handle, source_version_ref, provider_status, task_status.
- SourceStatus의 검색 조건·원문에 섞인 status 문자열은 관측 사실이 아니다.
- full snapshot/notes/title/due를 새 fact에 복사하지 않는다.
- unknown/missing/tampered/unbound/conflicting-version 대상에는 fact를 만들지 않는다.
- 같은 handle의 다른 version 중 임의 최신을 고르지 않는다. 다른 정상 handle은 유지 가능하다.
- run 격리는 기존 caller의 run-scoped snapshot 저장소가 소유한다. helper에 전역 자료를 주지 않는다.

## 사전 고정 비교 및 검수

1. 067의 actual compose 입력/원 FIRST 재사용. 현재 assembler/Schema로 wire 완전 재현을
   확인하고 같은 조회 결과에서 snapshot version이 정확히 일치해야 후보 FIRST1회를 실행한다.
2. 최소 합성 완료 Task control: 상태·메모를 묻는 입력과 completed snapshot으로
   baseline FIRST1 + candidate FIRST1을 비교한다. 실제 RU/Canonical Case 성공률로 계산하지 않는다.
3. 064 legacy-unbound 실패 기록은 재사용 negative control이다. 새 locator를 소급 부여하지
   않으며 fact0을 component gate에서 확인한다. missing/unknown/stale/conflict/본문 주입,
   비Task/미승인 Evidence, duplicate chunk는 모델 없이 검사한다.

총 신규 모델3호출, 각 FIRST1회, repair/retry0, concurrency1, timeout180초/호출.
qwen3.5:9b 실제 digest/ctx16384/seed20260923/think=false와 현재 compose 실제 옵션을
plan에 결속한다. temperature 미전송은 모델 기본값이며0으로 주장하지 않는다.
prepare와 execute를 분리하고 source/model/input/hash drift나 기존 결과 덮어쓰기를 거절한다.
실행 중 파일 수정·테스트·다른 모델0. 원 실패 Trial은 그대로 보존한다.

모양 일치가 아니라 요청한 상태·기한/메모·identity·근거 보존을 검수한다. 근거 없는 진행·완료·
WRITE, 누락, citation 탈락, 내부 metadata dump를 함께 검사한다. PARTIAL/FAIL도 보존한다.
개선 없으면 Prompt 상태 규칙을 덧붙이지 않고 후보를 비활성 유지한다.
개선되면 실제 upstream+Product compose consumer 연결을 다음 gate로 검토하며,
이 고립 FIRST 비교를 Graph/업무/Canonical92/Live PASS로 승계하지 않는다.
