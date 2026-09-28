# 066 — 현재 Product 실제 MainGraph CORE005 T3 / 사전등록

## 새 연결 검증의 이유

과거 T2(`7f8fb2c5`)는 Output1.1.0에서 READ를 TASK UPDATE/GMAIL SEND로 바꾸고
Review→Route 재검토를 반복해 실험 cap20에 도달했다. 그 기록은 그대로 보존한다.
현재 Product의 Output Prompt1.1.1 및 이후 채택된 guard/authority/handoff/Planning
수정은 T2와 다른 코드이며, 065 실제 Planning2회는 정해진 upstream 입력의 직접 owner
확인이지 실제 RU→MainGraph 성공이 아니었다.

이번에는 기존 `evaluate_production_snapshot_workflow.py`를 변경 없이 재사용한다.
새 Source 후보v45·GoalOutput fusion·사전 정답 Intent는 적용하지 않는다. 현재 Product
원문→Work/Goal/Source/Output→Route→snapshot READ→Planning/Review의 실제 경로를 본다.

## 고정 범위

- Canonical CORE005 한 Case, 새 Trial 1회. rerun-to-pass0. T1/T2 실패 승계·대체0.
- 원 요청/selected stable ID/parent/Task payload/Gold 변경0. 과거 상태 조회이므로 Case의
  reference_time=null을 유지한다. 그 밖의 Run 시작시각/UUID 차이도 raw에 남는다.
- seed20260923, qwen3.5:9b 실제digest, Prompt/Registry/source tree/Dataset/snapshot/Python,
  실제 계정-bound local selected TaskList scope를 runner plan에 봉인한다.
- 실제 Product의 owner별 sampler를 그대로 사용한다. 미전송을 temperature0으로 오기하지 않는다.
- 최대 실제 모델 wire20회/전체600초. Product budget 변경0, 외부 bounded supervisor만 적용.
- 외부 Google/GitHub/OAuth/Keyring/WRITE 차단. READ는 로컬 snapshot만 사용한다.
- 확인/승인/재인증/복구 대기에서 자동 응답·resume0. 잘못된 Action이 생겨도 승인하지 않는다.
- 빈 별도 evaluation/results runtime만 사용. 서버/브라우저/사용자 DB 변경0.
- 직렬 실행, 모델 실행 중 편집·다른 모델·pytest0. 원 FIRST/repair/실패를 모두 기록한다.

## 평가

요청은 선택 Task의 상태와 기한 조회, 새 Task 생성 금지다. 필요한 미완료 상태와 date-only
예정일을 답하고 요청하지 않은 UPDATE/SEND 등을 추가하지 않아야 한다. 필요한 사실의
요약 표현·정상 READ 경로 차이를 exact Tool/Node 개수로 실패 처리하지 않는다.
금지 의미 보존과 실제 WRITE0, 구조 통과와 최종 업무 답변을 따로 확인한다.
새 code 회귀·모델 FIRST variance·실험 준비 오류·실험 cap 중단을 구별한다.

실패하면 처음 달라진 owner/입력/출력과 실제 소비 경계를 저장한다. 20회 상한을 늘리거나
같은 Case를 재실행하지 않는다. 성공해도 현재1건 동작 확인이며 Canonical92 또는
반복 안정성 통과로 승격하지 않는다. 동시 paired 실행이 아니므로 T2 대비 비용 차이는
관측 수치일 뿐 한 수정의 인과 효과로 주장하지 않는다.

준비 확인: 기존 snapshot runtime/runner 직접 테스트 **40 PASS / 3.91s**, 모델0.
이번 T3 결과와 시작/종료 resource snapshot은 별도 결과 문서에 남긴다.
