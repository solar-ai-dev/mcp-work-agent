# 072 — 짧은 의미 입력의 추론 모드: 개선은 있으나 비용·잔여 범위 문제

판단: **추가 연결 검증 대상 / Product 활성화 안 함**. 같은3건의 자유 자연어 판정은
1 PASS/0 PARTIAL/2 FAIL → **2 PASS/1 PARTIAL/0 FAIL**이다. 독립 검수도 동일하다.
전체 RU/Tool Route/Canonical92 또는 업무 성공률로 승계하지 않는다.

## 조건·최초 출력

실행 SHA `b116c94b2d2f5016a411a8a52cc4333d89a29cde`, 기준
`072-ru-natural-reasoning-criteria.md`. 071의 실제 wire에서 think만 false→true로 바꿨다.
Core017→049→005 각 FIRST1, 총3회, repair/retry/rerun0. 3/3 stop/done=true,
시작·종료 binding 동일. 과거071 결과는 원 raw 그대로 사용했다.

| Core | 071 → 072 | 구체적 변화 |
| --- | --- | --- |
| 017 | FAIL → PARTIAL | 오후9시 오기와 Task를8월12일 자료로 한정하는 명시 변형은 사라짐. Task/Calendar/Draft 수신자 보존. 다만 '현재 진행 중인 작업 목록'이라는 좁은 표현이 남음. 실제 INCOMPLETE query가 생성됐다는 근거는 없으므로 FAIL로 확대하지 않음 |
| 049 | FAIL → PASS | Task 마감13시와 점검 Event 시작13시/1시간을 구분. Draft 수신자도 유지. '인계 작업 일정'이라는 자유 표현만으로 Event 오선택이라 판정하지 않음 |
| 005 | PASS → PASS | 선택 Task ID, 상태·기한 조회, 생성 금지 보존. 실제 상태·기한 발명 없음 |

017의 장소 정보 추가는 과한 정보 요구 관찰로 남긴다. 실제 Confirmation이나 Tool 호출은
없으며, Task 상태 범위가 바뀌었다고 확정할 수 없는 부분과 명백한 시간 변형을 구분한다.
049의 체크리스트는 '(가정)'으로 표시돼 실제 사실 확정으로 채점하지 않는다.
불필요 외부 행동 추가0, 실제 WRITE0. WorkUnit/Relation 구조·정확한 Resource/effect
선택을 생성시키지 않았으므로 이들 계약이 통과했다고 하지 않는다.

## 비용과 자원

| 같은3건 | calls | input/output tokens | reported latency |
| --- | ---: | ---: | ---: |
| 071 think=false 재사용 | 3 | 585 / 783 | 31,880ms |
| 072 think=true 신규 | 3 | 579 / 5,354 | 177,319ms |

지연은 단발 관측 **약5.56배**. 신규 wall177,390ms/load6,212ms, usage 누락0.
output tokens는 Ollama가 보고한 **숨겨진 추론 포함 생성량**이며 최종 표시문 토큰만이 아니다.
숨겨진 추론은 존재 bool만 기록했고 원문을 저장·검수·정답 복원에 사용하지 않았다.
payload는think 외 동일하다. 모델 template의 차이로 실제input tokens가6 줄어든 값은
그대로 기록하며 임의로 동일하게 맞추지 않는다.

qwen3.5:9b digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`,
Ollama0.34.0, Q4_K_M, temp0.05/seed20260923/ctx16384, presence override없음(default1.5),
stream=false. generation 직렬1, 중간 편집/테스트0. 시작GPU0MiB/41°C,
중간6375MiB/68%/66°C 및6377MiB/62%/70°C snapshot. peak 측정은 아니다.
071/072 직접28 PASS, scoped Ruff/mypy PASS. Product/Prompt/State/Schema/Graph 변경0,
Provider READ/WRITE0, Approval0, 실제workflow0이다.

## 결속과 다음 판단

- plan object hash `1cc3c0658d2c9e423024363c3af542db1525fc13b0289b9120281e430185a0ab`:
  `evaluation/results/072-ru-natural-reasoning-plan/preregistered-plan.json`.
- raw bytes hash `af183697e4a0e1b5aa68a5ca5d270dc2f115d7704cd02581cbcd38128a6f7186`:
  `evaluation/results/072-ru-natural-reasoning-t1/raw.json`.
- dataset/fixture는071과 동일하며 raw에 full hash를 결속했다.

과거 큰 Source Schema에서 완료되지 않았던 native reasoning도 작은 입력·자유 출력에서는
완료되고 일부 의미가 개선됐다. 따라서 무조건 모델 한계나 LoRA 필요성이라고 하지 않는다.
반대로 아직 모호한 범위와5.56배 비용, typed consumer 연결 미검증이 있으므로 Product의
think 기본값을 바꾸지 않는다. 정확한 자연어를 Product Source로 옮기는 진단은 가능하지만
그 변환에도 정보·범위·Work 판단이 필요하며 단순 deterministic lookup이라 하지 않는다.

이와 별도로 실제 코드 검토에서 일반 Task SEARCH도 상태 제약 없이 완료 Task를 제외하는
consumer 경계를 발견했다. 이는 이번 자연어 응답이 실제 Query로 변환된 결과가 아니다.
다음 작업은 그 결정적 축소를 실제 policy→plan→Connector→cache 경계에서 재현하고,
업무 Source의 범위와 Policy-only 중복검사의 미완료 범위를 구분해 최소 수정하는 것이다.
새 Prompt 규칙이나 동일 실패 재실행으로 이 코드 경계를 대신하지 않는다.
