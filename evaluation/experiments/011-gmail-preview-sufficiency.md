# 011. Gmail metadata preview를 업무 내용 근거로 승격하는 경계

기준 SHA `9440635a` + 010의 평가 harness patch. 010의 합성 연결에서
021/023/028은 Gmail 검색 preview만 Evidence로 선택하고 `SUFFICIENT`로
Work Analysis에 넘겼다. Work Analysis는 메일 본문 없이 제목·수신시각을
TASK/EVENT 사실로 오분류했다. 이는 Work Analysis 모델만의 문제가 아니라
Retrieval→Analysis 입력 부족이다. 015 비정책 Task 누락과는 별도 family다.

05의 기존 계약상 `is_metadata_only=true` 검색 preview는 확정 업무 근거가
아니다. 기존 detail 요구는 READ 답변과 thread reply에만 적용되어, Gmail을
참고해 Calendar/Task CREATE를 준비하는 혼합 효과에서는 선택된 preview가
`SUPPORTS`여도 통과했다. 이번 후보는 **이미 선택된 Gmail preview**가
내용 근거(`SUPPORTS`)인 경우에만 같은 Run 후보의 bounded DETAIL_FETCH를
요구한다. 새로운 Source/Route 판단이나 모든 business Source 조회 강제,
WRITE/Approval 변경은 하지 않는다. LLM의 다른 의미 판단을 덮어쓰지 않는다.

사전 비교: 동일 모델 9B·temperature 0·seed 1729·합성 Provider·고정 corpus,
직렬로 021/023/028 적용 요청 각 1 Trial, 014 비적용 기존 성공 대조 1 Trial.
기존 010 Trial은 Evidence fingerprint가 다른 이전 관측으로 보존하고
동일 입력 paired A/B 성공률로 표시하지 않는다. 신규 Trial에서는 첫 Query,
detail READ, 최종 Evidence의 metadata marker, Retrieval disposition,
Work Analysis 첫 structured fact와 최종 fact의 대상·시간·관계를 확인한다.
특히 단순히 detail 호출이 늘었다고 업무 성공이라 세지 않는다. 015의
비정책 Task 누락과 033/035 upstream 장애는 계속 별도 추적한다.

직접 영향 unit test와 Prompt/계약 정합성 확인 후 결과를 기록한다. 전체
92, 실제 Provider, Planning/Review, WRITE는 이 단계의 검증 범위가 아니다.

## 결과

첫 연결 021/023/028/014는 모두 사전 지정대로 실행했다. 014는 기존과 같이
Planning handoff·Evidence 2건으로 유지됐다. 적용 3건 모두 metadata preview를
`SUFFICIENT`로 넘기지 않고 `CONTEXT_BLOCKED`로 종료했으며, `gmail_get_thread`
READ는 0회였다. 021/023/028에서 Work Analysis 입력도 생성되지 않았다.
이는 **잘못된 충분성 통과를 막은 안전 회복**이지 업무 성공 개선이 아니다.

원인은 Gmail detail Need의 `route_id`가 비어 있는 데 있다. 혼합 요청에는
Google Calendar/Task/Gmail Route가 함께 있어 `select_followup_routes`가
미결합 GOOGLE Need를 어느 Route에도 할당하지 않았다. 05의 기존 frozen Route
계약에 맞춰 유일한 Gmail detail-capable Route ID만 이 Need에 결합한다.
다중 Gmail Route가 있으면 임의 선택하지 않는다. 직접 영향 테스트 후 **021
1건만** 연결 재생해 detail READ가 실제 생성되는지 확인하고, 그렇다면 023/028을
각 1회로 확장한다. 새로운 전체 E2E·실제 Provider는 실행하지 않는다.

후속 연결에서 유일한 frozen Gmail detail Route ID를 Need에 결합하자, 021은
Gmail detail READ 1회/metadata-only Evidence 0건/Work Analysis fact 10건으로
도달했다. 023/028도 각각 detail READ 1회/metadata-only Evidence 0건,
Work Analysis fact 6/10건이었다. 021 메일 본문의 8/18 제안과 8/19 확정,
023 지연 이틀과 배달일 미확정, 028 `내일 30분`은 각각 별도 사실로 확인했다.
다만 028의 `업무시간` 제약은 Work Analysis route reason에 드러나지 않았고
RU required_information에는 있었다. `analysis_requirement=NONE`인 세 입력은
Calendar conflict policy 때문에 effective Work Analysis로 갔으므로
relation 0개만으로 의미 실패라고 하지 않는다. 014는 앞 Trial에서 기존
Planning handoff/Evidence 2건을 유지했다. **본문 확보와 인접 연결은 확인**;
전체 업무 성공·실제 Provider READ는 아직 미검증이다. 비교 Trial의 Evidence
fingerprint가 다르면 같은 입력 반복으로 세지 않는다.
