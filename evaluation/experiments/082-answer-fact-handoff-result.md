# 082 — 실제 compiled Planning 연결: 4개 보존

실행 SHA `f98d2d87`. **component gate 4/4 PASS**, 신규 모델·Provider·WRITE·DB Run 생성0.
081에서 이미 얻은 선택값4개를 모두 재사용했으며 새 모델 Trial로 세지 않는다.

## 실제로 검증한 구간

067의 exact pre-Planning checkpoint를 read-only로 읽었다. 축약된 compose 입력으로
RetrievalResult를 역추정하면 collection의 Resource handle이 사라져 입력이 달라졌기
때문에 원 checkpoint를 사용했다. 원 DB·checkpoint·081 raw는 변경하지 않았다.

실제 `PlanningSubgraph.build()`의 outline/compose Node가 current component Run의
`RunScopedEvidenceStore`에서 exact version snapshot을 얻었다. 입력 전체가 원081과
일치하는 invocation에서만 저장된 선택을 renderer에 전달했다. 기존 Product validator,
compiled final_result, 같은 Planning owner의 Answer artifact materialization,
실제 terminal intent builder까지4개 답변이 그대로 유지됐다. Terminal LLM 호출0.

- 실제 CORE005 selection2개: `미완료 / 예정일 2026-08-10` 보존.
- synthetic completed selection2개: `완료 / 원문 메모` 보존.
- 각 replay에서 입력 불변, 기존 validated draft와 exact equality, snapshot Run/version
  결속을 확인했다. 이전 Run을 재개한 것이 아니라 새 in-memory component 범위다.
- actual에는 원 checkpoint State, synthetic에는 명시적인 ANSWER route fixture를 사용했다.
  실제 새 RU/ToolRoute 성공, Main/Supervisor merge, DB terminal commit/UI 전달은 미검증이다.

## 회귀·한계

직접13검사 PASS. 다른 Run·snapshot 누락·stale version·hash mismatch·동일 Resource의
상충 version·미승인 ref·자유 value·빈 선택·개요 drift를 검사했다. 필드 누락은 구조상
통과할 수 있음을 별도 반례로 고정했다. component PASS가 의미 PASS를 자동 뜻하지 않는다.
082 raw의 semantic_verdict는 `NOT_EVALUATED`로 유지하며081 의미 판정을 다시 만들지 않았다.

Ruff PASS. 첫 mypy 실행에는 scripts module 중복 경로 오류가 있었고,
`--explicit-package-bases`로 실제 검사한 결과 resolved-map의 key typing1건을 발견했다.
gate 실행 뒤 runtime 동작이 없는 annotation/cast만 정리했다. 실행 원결과와 당시 support
hash는 그대로 보존한다. 이후 연결/후보 인접74검사 PASS에13개도 포함된다.

추가 read-only 조사에서 terminal budget merge가 stale 값을 소비할 가능성을 보았으나,
실제 physical-node 분리 compiled probe에서는 context=None으로 시작해 State budget8을
그대로 유지했다. 직접 함수에 stale context1/State7을 넣는 합성 재현만으로 Production
결함이라고 결론내리지 않았고 budget/WRITE 소비 코드는 수정하지 않았다.

**판단:** 값 권한을 renderer에 둔 방식은 이 연결 구간에서 유효하다. 일반 ANSWER
적용 범위까지 증명한 것은 아니므로 Product는 유지한다. 다음083은 규칙·classifier 호출을
추가하지 않고 같은 compose 호출이 사실 참조/서술형 중 선택하는 별도 후보를 검증한다.
적절한 서술형도 정상으로 인정하고, 잘못된 참조 선택을 fallback으로 구제하지 않는다.

raw: `evaluation/results/082-answer-fact-handoff-t1/raw.json` (local ignored).
SHA256 `5de43601729d0b327a08f43ffec23cd351ba95a66d36a2dbebc1f96f6ea07ab5`.
Product source/활성 Prompt/Schema/State/Node/Edge 변경0. Dataset/Gold 변경0.
