# 065 — 조회 실패를 정상 빈 결과로 승격한 Planning 소비 경계 수정

기준 `87d171fe`. 직전 실제 모델 진단과 분리된 deterministic 코드 결함이다.
실제 064/065 raw에서 이 최종 모순 답변을 관측했다고 주장하지 않는다. 현재 생산 코드와
Canonical05/15의 계약으로 반례를 만들었고, 모델 호출 없이 최초 손실을 재현했다.

## 원인과 수정

```text
project_acquisition_result: NOT_FOUND/PERMISSION_DENIED, FAILED, checked_read_count=1
→ finalize_retrieval: FAILED + failure_kind + observed_resource_count=0 유지
→ PARTIAL/Evidence0 ANSWER는 정상 Planning 진입
→ Task formatter: 빈 Evidence를 '할 일 미발견'으로 단정
→ 공통 scope notice: 실패한 호출 횟수도 '확인한 범위에서 미발견'으로 표현
```

마지막 두 소비 경계가 실패 원인이다. 뒤에 '읽지 못했으며 검색 결과가 없다는 뜻은
아닙니다'를 붙여도 앞의 단정은 사라지지 않았다. READ 시도 횟수는 성공 횟수가 아니다.

- Task formatter의 optional 내부 인자로 기존 RetrievalResult를 전달한다. 빈 Task 답변은
  SUFFICIENT + 실제 `task` Source의 정상 COMPLETE/failure 없음 + 명시적 checked>0/
  observed=0 + scope_complete/EXHAUSTED일 때만 허용한다. TaskList 성공은 Task0건의 근거가
  아니다. 미시도/실패/부분 범위/관측값 누락/조회됐으나 Evidence 미선택은 기존 compose로
  전달한다. 없는 metadata를 만들어 과거 checkpoint를 변환하지 않는다.
- outline/compose 양쪽이 같은 입력을 소비한다. Evidence가 있는 기존 Task formatter와
  정상 완료된0건의 호출0은 유지한다.
- 공통 scope 안내는 정상 COMPLETE/PARTIAL, failure 없음, 명시적 관측값을 가진 Source의
  조회 횟수만 합산한다. 전체 완료 여부는 필터 전 모든 Source를 기준으로 유지한다.
  성공한0건1회 + 실패4회는 '확인한 범위1개/전체 미완료'와 실패 안내이지 5개 성공이 아니다.
- Canonical15는05의 기존 실패≠빈조회/Source별 상태 계약을 해당 소비 경계에 명시한다.
  Prompt/Schema/State/Node/Edge/Approval/Execution/Verification 의미 변경0.

## 직접 검증

최초 고정10개: 수정 전 **9 FAIL / 1 PASS (0.42초)** → 동일10개 **PASS (0.22초)**.
호출1을 주장하는 성공 fake가 아니라, 수정 전 실제 formatter가 composer를 건너뛰고
잘못된 문구를 만들거나 실제 scope notice가 실패 count를 합산한 assertion 실패다.
정상 완료된0건 control은 전후 모두0-call이다.

추가 TaskList-only, optional count 누락, unknown continuation 등을 포함한 직접15개
PASS/0.25초. 현재 test fixture는 계약 enum CRITERIA를 사용한다. 그 enum 정합화는
baseline consumer 분기에 영향을 주지 않는다. 기존 Task empty unit fixture에는 실제
완료·0건 관측값을 추가했으며 정상 empty 기대를 삭제하거나 완화하지 않았다.

단일 pytest process 관련 회귀 **2,251 PASS / 14.20초**:

```text
python -m pytest tests/unit/application/agents tests/unit/application/use_cases/run
  tests/unit/adapters/langgraph tests/component/langgraph/test_production_agent_subgraphs.py
  tests/component/langgraph/test_calendar_snapshot_answer_handoff.py
  tests/evaluation/test_read_answer_handoff_diagnostic.py -q
```

전체 repository 테스트가 아니며 직접15개와 중복되어 합산하지 않는다. 모델/Provider/
서버 재시작0. 검사에는 fake composer를 사용했고, 실제 모델의 실패 설명 품질이나
Canonical92 성공률을 갱신하지 않았다. Task partial fallback은 정당한 답변 작성을 위해
기존 semantic 호출이 필요하므로 호출 감소 최적화라고 주장하지 않는다.

별도 연결3개 **PASS/0.64초**: 실제 `project_acquisition_result → finalize_retrieval →
compiled PlanningSubgraph`에서 NOT_FOUND/PERMISSION_DENIED의 FAILED·checked1·observed0·
Work binding을 그대로 소비한다. compose fake1회로 실패 안내를 유지하고 빈 조회 단정은
없다. 정상 complete empty counterexample은 같은 producer 경로로 호출0을 유지한다.
RequestIntent는 현재 V3 validator를 통과하며, Sufficiency는 명시적 fixed typed 입력이다.
이는 실제 Retriever/LLM이 충분성을 판단한 성적이 아니다. 변경Python6파일 Ruff/Mypy 및
diff whitespace 검사 PASS. 제품 변경은 Planning 내부3파일이다.

## 한계와 다음 선택

확정된 원인에 대한 Product 수정은 채택한다. 새 규칙이나 natural-language parser는 없다.
LLM이 생성하는 부정확한 실패 설명 자체를 이 코드 수정으로 모두 막았다고 주장하지 않는다.
동일 실패 Trial 재실행·새 Prompt 후보·추가 모델 호출은 없으며, upstream Source/Output
잔여 오판과 전체 업무 성공은 별도 검증 대상이다.
