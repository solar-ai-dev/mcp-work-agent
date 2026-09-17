# 034. 029 저장·resume와 원격 Trace의 근거 부족 최초 경계

현재 진단 기준 `021224fa`, 관측한 백엔드 코드 SHA는 **이전**
`d59b69d124845967c49e10a87fc4af7757f98fae`다. 029의 격리
Domain Run `ca7e3aad-6412-40d3-83df-23b0af71126d` 데이터베이스를
읽기 전용으로 대조했다. 새로운 Domain Run, 백엔드 start/replace,
Provider WRITE는 0. 저장된 원문·전체 State·Secret을 외부로 복사하지 않았다.

허용된 Preview `payload.title` 수정은 Domain Action `MODIFIED`와
checkpoint `__modify_review_changes__`, 수정된 `planning_result`에
같은 Action/path/value로 존재했다. 즉 이 Live BLOCKED의 첫 결함을
“수정 제목이 저장 또는 resume에서 사라짐”이라고 할 수 없다. resume
Review는 RECHECK가 아니라 초기 inspector 세 개를 호출했고,
`RETRIEVE_MORE`의 Task 내용 EVIDENCE_GAP을 냈다. Context Retrieval
후 `BLOCKED`로 끝났으며 수정에 대한 정상 승인 대기 복귀는 증명되지
않았다. 022의 동결 입력에서 발생한 옛 제목 기준 허위 ISSUE와는
Evidence fingerprint 및 finding이 다르다.

동일 checkpoint의 Tool Route input에는 TASK_LIST와 TASK가 모두 있다.
하지만 Retrieval query attempt 여섯 개 중 TASK는 0, TASK_LIST는 1이고,
source status에서 TASK item은 없으면서 coverage=SUFFICIENT/missing=0이다.
Review에 공급된 Task 근거는 Task item 본문이 아닌 Task list 제목만이다.
따라서 요청의 작업 **내용** 부족은 Review의 제목 권위 문제가 아니라
Route→Query 선택 또는 Retrieval 충분성 경계의 별도 결함 가능성이
높다. 이 단일 Live Run으로 TASK를 모든 업무 Source에서 강제할 근거는
없으므로 이 작업에서 정책·Route 보정은 하지 않는다. 015 Task 미조회와
같은 family인지도 동일 Query input/반례 비교 전에는 확정하지 않는다.

LangSmith CLI의 설치된 실행 파일은 `trace` 명령을 제공하지 않았다.
Python SDK로 기존 전용 project
`google-work-agent-review-d59b69d1`의 원격 trace
`01a0ac78-1279-74f1-ba48-483ac9472881`을 조회했다. 19개 하위 Run,
LLM 5개(두 retrieval.plan_query + 초기 Review 세 inspector), trace
metadata code SHA `d59b69d1`을 확인했다. 로컬 029의 Domain 상태·호출
계층과 일치한다. 이 조회는 **새 제품 SHA의 Live 검증이 아니다**.

외부 메일을 제거한 021/031 동결 합성 입력의 Goal 첫 출력은
EVIDENCE_GAP과 동시에 “일정을 생성할까요?” CONFIRMATION을 내어
aggregate가 CONFIRM으로 갔다. 사용자 생성 의도는 이미 명시된 반면
외부 메일 자료가 부족한 상태이므로 결함 분류 자체가 잘못됐다.
반면 정상 근거·정상 Plan은 PASS, 근거가 있는 날짜/금지 오류는 ISSUE다.
Review의 이 분류 오판과 Live의 TASK 내용 부족은 같은 입력 반복이나
하나의 수정 원인으로 합치지 않는다.
