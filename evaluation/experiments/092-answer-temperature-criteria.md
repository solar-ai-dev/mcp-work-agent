# 092 — 답변 owner의 temperature 단독 소형 진단

088/090/091의 답변 필드·표현 선택 오류를 비교한다. 090 공통 문맥 삭제는 실패를 다른
요청으로 옮겼고091 조회 alias 생략도 과잉 선택을 해결하지 못했다. 같은 입력 삭제나
Prompt 문구/정답 Schema를 추가하지 않는다.

현재 Planning 및 평가 answer-choice는 temperature를 전송하지 않아 모델 기본1을
사용한다. Goal0.1/Source0.05/Output0의 기존 결과를 이 답변 owner의 sampling 검증으로
승계하지 않는다. 이전 Source presence 및 effect-prohibition temperature 기각 기록은
그대로 보존하며, 이번 진단이 공통 sampler 변경의 근거가 되는 것도 아니다.

## 사전 고정

- 088 실제 raw의 첫 세 입력, lookup→완료·메모→재작성 각1개=신규 FIRST3.
  동일 입력의088 T1 세 결과는 역사 참조이지 새 paired baseline 실행이 아니다.
- 반드시088 원본 full input, 공통 문맥, PromptRef, ROLE, Schema/순서와 Evidence/snapshot을
  사용한다.090 문맥 삭제·091 alias 생략을 중첩하지 않는다.
- 바뀌는 wire 값은 `options.temperature=0` 하나다. presence/default1.5,seed20260923,
  ctx16384,think=false,model/digest/metadata·기타 option은 그대로 유지한다.
- 각 입력 FIRST1, repeat/repair/retry0, concurrency1, 각 전송 timeout180초. 세 호출을
  넘지 않으며 실패를 다른 Trial로 대체하지 않는다. transport/구조 오류면 기존 recorder
  정책으로 남은 호출을 미실행하고 이유를 남긴다. 의미 실패는 전체 고정집합에 포함한다.
- HEAD·source·기존 raw·Dataset/fixture·reference time/fault binding·original/candidate ordered
  wire를 plan hash로 결속한다. exclusive plan claim과 종료 binding 검증을 유지한다.
- raw transport 진단으로 등록 router/Main Graph/업무 성공/Canonical92/배포에 승계하지 않는다.

## 판정

기존과 같이 lookup은 상태·기한만, 완료·메모는 실제 완료와 메모 의미, 재작성은 확인
항목의 짧은 체크리스트와 원문 문장 인용 금지를 평가한다. FACT/PROSE를 정답으로
강제하지 않는다. 구조 VALID와 의미 PASS/PARTIAL/FAIL을 분리한다.
첫 출력과 materialized answer를 함께 검수하고 calls/tokens/latency·회귀를 기록한다.

모두 좋아져도 단발 진단만으로 sampler나 후보를 Product에 반영하지 않는다. 같은
등록 경계의 고정 반복·인접 control 검증을 거쳐야 한다. 개선이 없으면 temperature
수치를 연속 탐색하거나 presence까지 섞지 않고 이번 축을 기각한다.
Product/활성 Prompt/State/Approval/Execution 변경0, Provider READ/WRITE/SEND0.
