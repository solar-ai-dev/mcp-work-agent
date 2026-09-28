# 083 — 한 compose 호출의 사실 참조 / prose 선택

## 가설

081은 고정 lookup 두 입력에서4/4였지만 일반 업무 적용 범위는 정의하지 않았다.
Task/READ/analysis NONE 또는 Source required_information만으로 직접 조회를 판별하지
않는다. 같은 compose owner에서 모델이 질문의 의미에 맞게 사실 참조 또는 기존 prose를
선택하도록 출력 계약을 확장한다. 별도 classifier/Node/추가 호출·lexical gate는 없다.
082의 실제 Planning handoff gate가 통과하기 전에는 새 모델 실행을 시작하지 않는다.

## 사전 범위·예산

- 기존081 actual CORE005 상태·기한 / completed 상태·메모는 입력·snapshot 그대로 사용.
  후보 각 FIRST2회, 기존081 refs4회와 역사 prose각1회를 분리 비교한다.
- 강한 반례:067 Task의 기존 facts/snapshot을 재사용한 **새 합성 사용자 요청**은
  메모의 확인 항목 정리와 원문 문장 그대로 인용 금지를 요구한다. Canonical Case를
  수정하거나 새 Canonical ID를 만들지 않는다. 합성 typed Intent/outline을 명시하고
  실제 RU가 생성한 State로 기록하지 않는다. 계정 발급·장비 수령의 확인 의미가
  유지돼야 하며 수행 완료를 발명하면 실패다. 특정 정리 형식/표현 하나만 강제하지 않는다.
- 이 반례에는 기존 raw baseline이 없으므로 현행 compose baseline FIRST2와 후보
  FIRST2를 새로 고정한다. 총 새 모델 호출 **8회**, 동시성1,repair/retry0,timeout180초.
- 순서:actual1,completed1,반례baseline1,반례candidate1,actual2,completed2,
  반례baseline2,반례candidate2. 환경/transport 중단 외에는 실패도 끝까지 기록.
- 같은9B digest/Ollama0.34.0, seed20260923/ctx16384/thinkfalse,
  temperature 미전송(모델기본1)/presence 미전송(기본1.5), strict schema.
  기준선과 후보의 실제 input·options를 대조하며 출력 계약/그 책임 설명 외 조건은 고정.

## 출력·검증

`FACT_REFERENCES={mode, items}` 또는
`PROSE={mode, schema_version:2, answer, evidence_refs}` 중 하나다.
refs는081 helper를 그대로 사용하고, prose는 mode만 제거한다. 둘 다 현행 Product
compose validator/normalization/partial-scope를 통과해야 한다. mixed branch, 외부 ref,
자유 value는 구조 실패다. []는 NO_DRAFT이며 다른 branch로 자동 fallback하지 않는다.

판정은 최종 요청 의미다. lookup에서 정확한 prose도 PASS이며 참조 방식 사용률과
값 재생성 위험은 별도다. 반례에서 refs 선택 자체가 실패 사유는 아니지만 실제 renderer가
원문 인용만 내어 정리·인용 금지 조건을 잃으면 FAIL이다. 모델의 잘못된 선택을 validator가
의미 보정하지 않는다. 누락·과잉 사실·부정·effect·모드·구조·비용을 모두 보존한다.

Product source/활성 Prompt/State/Graph/Approval 변경0. Provider/WRITE/실제 업무 실행0.
고정 Node input 진단이며 Canonical92/전체 Workflow 점수로 승계하지 않는다.
raw는 evaluation/results/083-*에 봉인하고 완료 후 결과·판정과 다음 선택을 기록한다.
