# 068 — completion fact 추가 입력: 전달 성공 / 생성 의미 개선 없음

판단 **REJECT(효능 없음)**. Product source/Prompt/State/Node/activation 변경0.
비활성 후보는 재현 자료로만 보존한다. Prompt 상태 규칙이나 답변 후처리를 추가하지 않는다.

실행 SHA `c060c799f3deed4cafb2b0f61120644198c72243`, plan object SHA256
`85e3051bcdf0597375ce5bb2265bf8a7e0432974598dc8afda1907d55c7f2bbb`.
고정 신규3 FIRST, 각1회. 원067 baseline은 재사용,064는 version 없는 negative로 유지했다.

| 입력 | 기존 → 후보 | 관측 |
| --- | --- | --- |
| 실제 CORE005의 frozen compose 입력 | PARTIAL → PARTIAL | 후보도 needsAction을 진행 중이라고 표현. 대상·date-only·citation은 보존 |
| 합성 completed Task의 상태·메모 | PASS → PASS | 두 answer/citation 완전히 동일, 완료 상태와 메모 정확 |
| legacy064 no-version | component negative 유지 | 새 fact0, 모델 재실행0, 소급 locator 추가0 |

후보의 `task_status=incomplete`는 plan에만 있는 것이 아니라 실제 wire의 input과 assembled
instruction 양쪽에 존재한다. 같은 Run의 exact Evidence handle/version에 결속됐고, 원문과
기존 Evidence도 유지됐다. 그럼에도 FIRST에서 “진행 중(needsAction)”이 나왔다.
normalizer는 이 문장을 새로 만들지 않았다. **전달 실패가 아니라 compose의 생성 의미 오류**가
이번 후보에서도 남았으며 구조 VALID3/3를 의미 PASS로 세지 않는다. 독립 검수도 같은 결론이다.

| 셀 | input/output tokens | reported ms |
| --- | --- | --- |
| 원067 baseline(재사용) | 4,873 / 119 | 7,209 |
| CORE005 후보(신규) | 5,239 / 123 | 15,000 |
| 합성 completed baseline(신규) | 2,771 / 49 | 3,559 |
| 합성 completed 후보(신규) | 2,989 / 49 | 3,578 |

신규 합계3calls/input10,999/output221/reported22,137ms, usage 누락0.
기존 model/Ollama/options 유지: 9B digest `6488c96f…`, Ollama0.34.0,
ctx16384/seed20260923/think=false. temperature 미전송은 model default1이며0이 아니다.
역사 baseline과 cold/load 상태가 달라15초 대7초를 순수 후보 지연으로 해석하지 않는다.
본문·출력 Schema는 동일하고 별도 evaluation input contract/PromptRef만 사용했다.

- direct/adjacent tests95 PASS, Ruff/mypy PASS. wrong-Run, unknown/null/missing,
  hash/stale/conflicting version, notes 위조, 승인된 outline 밖 Evidence, legacy negative 검증.
- end source/model/HEAD 결속 동일. generation 중 편집·pytest·다른 모델0.
- 종료 직후 GPU6383MiB/0%/52°C(peak 아님). 외부 Provider READ/WRITE0, 승인0, rerun-to-pass0.
- raw `evaluation/results/068-task-completion-fact-t1/raw.json` SHA256
  `3a72e4d1c62519ff69559011f7e60d83fdb9e9b25104c96818123c2deda91161`.

한 보조 fact 표현의 기각이지 모든 typed handoff의 실패나 모델 능력 한계 증명은 아니다.
Canonical92/actual MainGraph 재실행/업무 종단 성공은 평가하지 않았다. RU 실패도 해결하지 않았다.
다음은 원 T3의 실제 frozen checkpoint가 확보된 Query exact-ref 수정의 모델 gate다.
coarse Prompt category로 Route를 역추정하지 않고, 원 FIRST와 동일 input을 재구성한 근거로만 진행한다.
