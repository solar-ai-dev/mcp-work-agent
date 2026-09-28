# 065 — Calendar READ formatter의 Source authority와 답변 범위 복구

기준 Product `9c5a4d38297938bbabb2dc8eb5189d6fe9a41ae1`. Review 후보 실험의
모델 점수와 별개의 코드 결함이다. 새 Prompt 후보나 모델 호출 없이 발견·재현했다.

## 최초 손실

| 경계 | 실제 결함 | 최소 수정 |
| --- | --- | --- |
| Calendar payload → normalized excerpt → schedule formatter | normalizer가 실제 시각 뒤에 location/description을 붙이며, formatter가 모든 줄을 재파싱해 뒤의 `start:`/`end:`/`title:`를 Provider metadata로 승격 | 이미 존재하는 same-Run/version Source snapshot resolver를 사용. excerpt와 segment 정규화는 변경하지 않음 |
| 확정 Source 정보 → formatter 선택 | 요청에 시간 관련 단어가 있으면 Source가 장소 등도 요구해도 시간만 조기 반환 | Source와 USER_REQUIREMENT의 required_information 전체를 현재 formatter 표현 범위와 대조. 지원하지 않는 정보는 기존 compose owner에 전달 |

실제 `normalize_segments → outline_answer/compose_answer` 직접 테스트에서 description의
다른 제목·2030년 시각·timezone이 원래 2026년 시각을 덮는 것을 확인했다. 또한
`start/end/location` 입력, snapshot 없음, stale snapshot에서도 semantic owner를 건너뛰었다.
수정 전 **4 FAIL / 1 PASS (0.38초)**, 수정 후 동일 5개 **PASS (0.22초)**다.
미지원 함수 인자로 발생한 TypeError나 가정한 모델 오답을 baseline 실패로 세지 않았다.

## 보존한 계약

- Source/Goal/Output 의미를 새로 판단하지 않는다. 기존 typed 정보가 title/start/end/timezone으로
  모두 표현되고 start와 end를 모두 요청한 경우만 기존 full-interval formatter가 담당한다.
  start-only/end-only는 추가 시각을 코드에서 덧붙이지 않고 기존 작성 owner에 맡긴다. Constraint의
  `str | list[str]` 표현을 모두 보존하며 자연어 parser나 새로운 alias는 추가하지 않는다.
- `언제/시간/date` 등 원문의 lexical schedule 판단을 제거했다. 원문은 변경하지 않고
  표현 언어 선택에만 계속 사용한다.
- 기존 선택 ID 또는 confirmation 검색 후 SUFFICIENT·단일 target 결속을 유지한다.
- snapshot은 Resource/parent/Provider version/content hash가 Evidence locator와 결속된
  경우만 사용한다. 누락·변경·다른 version은 기존 LLM 작성 경로로 보낸다. 새 snapshot을
  추측하거나 과거 checkpoint를 변환하지 않는다.
- 승인된 outline citation subset 검사, PARTIAL 안내, Approval/Execution/Verification 유지.
- snapshot은 내부 인자로만 전달하며 Prompt에 넣지 않는다. Source/State/Schema/Node/Edge/
  Prompt/Dataset/Gold 변경0. Canonical15는 기존05 snapshot authority와 formatter 범위를 명시했다.

## 검증 범위

직접 테스트는 합성 Provider payload와 실제 normalization/Planning 함수를 사용한다.
fallback composer는 fake이며, 호출·원문/Intent/Evidence 전달을 검사한다. fake 답변을
실제 모델 업무 성공으로 보고하지 않는다. 단순 시간 조회는 0-call 경로를 유지하고
미지원 정보·legacy snapshot 부재에서는 원래 의미 작성 owner의 호출이 필요하다.

최종 직접·인접 **88 PASS / 0.76초**. selected/confirmed identity, 서로 다른 snapshot
version, truncated excerpt, scalar/list Constraint, 두 Source 중 하나의 미지원 정보,
start-only/end-only, 원본 불변을 포함한다. 실제 `RunScopedEvidenceStore → compiled
PlanningSubgraph → outline/compose` 2개에서는 schedule-only의 semantic 호출0과
location fallback의 compose 호출1, snapshot의 Prompt 비노출을 확인했다.

다음 관련 회귀는 **2,227 PASS / 12.70초**, 단일 process로 실행했다. 앞 88개와 일부
중복되므로 합산하지 않는다. 전체 repository pytest가 아니다.

```text
python -m pytest tests/unit/application/agents tests/unit/application/use_cases/run
  tests/unit/adapters/langgraph tests/component/langgraph/test_production_agent_subgraphs.py
  tests/component/langgraph/test_calendar_snapshot_answer_handoff.py -q
```

변경 Python6파일 Ruff/Mypy와 diff whitespace 검사 PASS. 제품 코드는 기존 formatter와
그 compose caller 2파일만 변경했다. 이전 excerpt-only 성공 fixture는 실제 snapshot과
Source 요구가 결속된 fixture로 교정했고, snapshot 부재는 별도 fallback 반례로 남겼다.
모델 출력 정답을 바꾸거나 Dataset·Gold를 수정하지 않았다.

실제 모델의 답변 완전성, upstream RU의 Source 선택 정확도, 전체 Graph 업무 성공률은
이 검증으로 증명하지 않는다. 모델 재실행·실제 Provider READ/WRITE/SEND·승인 실행0.
rerun-to-pass0. 테스트는 단일 pytest process, CPU만 사용한다.
검증 중 관측 GPU0MiB/42°C, 여유 RAM19.57GiB였다(peak 측정은 아님).

WorkAnalysis confirmation의 return 이후 cleanup 줄도 별도로 조사했지만, 정상 gap 재개는
새 resolution으로 교체하고 상위 재진입에는 local 채널이 전달되지 않았다. 따라서 잔류
값을 곧바로 실제 의미 오적용으로 주장하거나 이번 수정에 섞지 않았다.
