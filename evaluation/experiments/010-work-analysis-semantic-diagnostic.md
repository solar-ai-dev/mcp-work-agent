# 010. Work Analysis 의미·동일 입력 진단

기준 SHA `9440635a`, corpus `canonical92-v8-5a49aa00-ecf32ffc82`.
제품 Prompt·Schema·Node 로직은 바꾸지 않고 평가 harness만 확장한다.
008의 028 두 Trial은 Evidence 5건/4건으로 다른 실제 입력이었으므로 동일 입력
반복 근거에서 제외한다. LoRA, 실제 Provider WRITE, 전체 92 E2E는 범위 밖이다.

## 사전 조건과 판정 기준

합성 Provider READ를 사용하는 현재 RU→Tool Route→Retrieval을 사례당 한 번만
실행하고, Work Analysis 진입 GraphState와 EvidenceStore를 in-memory로 고정한다.
동일 입력 확인에는 전체 State+resolved Evidence의 SHA-256 fingerprint를 쓴다.
Work Analysis Trial마다 같은 State의 deep copy, 동일 9B 모델·digest,
temperature 0·seed 1729, 같은 Prompt manifest·run semantic clock 시작점과
독립된 동일 RunBudget을 사용한다. 무거운 실행은 직렬이다. fingerprint가 다르면
반복으로 세지 않는다. Provider 지연과 GPU 부하는 별도 관측이며 완전히 고정된
실험 환경이라고 주장하지 않는다.

개발 비교 집합은 021(명시 일정/메일·Task), 023(다른 대상·명시 일정),
028(상대 날짜·업무시간), 033(Task deadline), 035(메일 안의 명령 무시)다.
각 적용 입력 1 Trial, 028만 동일 입력 2 Trial을 사전에 고정한다. 상위가
Work Analysis에 도달하지 못하면 `UPSTREAM_NOT_REACHED`로 남기고 분모에서
제외한다. 014의 기존 Planning 직행은 비적용 대조, 015의 비정책 Task 누락은
별도 Retrieval 실패 family로 추적한다. 실패 뒤 성공할 때까지 추가 반복하지
않는다.

평가 축은 (1) 첫 structured inference의 Schema 성공과 의미 정확성,
(2) 결정적 보충·validator·repair/revision 후 최종 의미,
(3) 입력 부족과 실제 업무 달성 가능성,
(4) 호출 실패·지연이다. 모델의 raw provider completion은 이 경계에서 얻지
못하므로 `first structured inference`를 raw completion으로 부르지 않는다.
원문·근거 대비 사실의 주체/상태, 일정의 날짜·시각·소요시간, 부정과 인용된
명령의 비승격, 요청한 업무 관계가 맞는지 수동 근거 검토한다. 사실·관계의
개수나 validator PASS만으로 semantic-valid 처리하지 않는다. 다른 합법적
업무 표현은 허용하고 Gold는 참고만 한다.

상세 structured inference·WorkAnalysisResult는 명시적 capture 옵션을 사용한
경우에만 ignored `evaluation/results/`에 기록한다. 커밋에는 비민감 요약과
실패 유형/시도 방법/조건·결과·판정·재시도 조건만 남긴다. 의미 판정이 유효한
실제 출력을 다음 Planning→Review consumer로 전달할지는 이 결과 후 결정한다.
028의 180초 실패는 이번 동일 입력 Trial의 typed error code·dispatch 여부·
첫 입력 크기·지연으로 별도 판정한다.

첫 관측에서 023의 첫 추론이 Evidence wrapper 필드를 31개 TASK 사실로 복사했다.
따라서 별도 단일 변수 후보 B를 추가로 비교한다. A는 현재 전체 EvidenceDraft를
`extract_work_facts`에 제공한다. B는 **같은 고정 입력**의 Evidence 각각에서
`evidence_id`, `resource_handle`, `excerpt`, `is_metadata_only`만 전달한다.
원문·Intent·availability·Prompt·출력 Schema·모델은 유지한다. 021/023/028
각 1회 A의 첫 structured inference와 B의 1회 inference를 비교하며, B는
제품 경로에 아직 연결하지 않는다. wrapper 복사·사실 누락·대상/시간 왜곡,
토큰·지연을 함께 보고 B가 한 사례만 좋아지면 채택하지 않는다.

## 결과

028은 고정된 현행 RU→Retrieval Evidence 4건과 같은 State/Evidence fingerprint
`ebdf0b...`에서 Work Analysis 2 Trial을 실행했다. 둘 다 완료했고 각 5 LLM
호출, 70.3/52.3초였다. 첫 추론의 fact는 각 8건, relation은 0건이었다. 이
경로는 effective policy-only이므로 relation 0만으로 실패가 아니다. 하지만
Gmail은 metadata preview만 있었고 지연 본문 사실은 확인할 수 없었다. 과거
008의 Evidence 5건에서 180초 timeout과는 **다른 입력**이므로 회복·반복 성공
증거로 혼합하지 않는다.

다른 입력 한 Trial씩: 021은 Evidence 5건/Work Analysis fact 7건/5호출,
61.4초; 023은 Evidence 4건에서 첫 추론이 Evidence wrapper의 메타 필드까지
31개 TASK fact로 복사했다(131.7초). 033은 Retrieval `CONTEXT_BLOCKED`,
035는 pre-READ `RETRIEVAL_ROUTE_SCOPE_VIOLATION`으로 Work Analysis 분모에
들어오지 않았다. 이 결과는 다섯 요청 모두의 의미 성공률을 선언하기 위한
샘플이 아니다. 원인 축은 입력 부족과 모델의 fact extraction 오류를 분리한다.

023 compact Evidence 후보는 같은 frozen 입력에서 A가 fact 7건을 완료했지만
B의 첫 Provider dispatch가 180초 `PROVIDER_TIMEOUT`으로 끝났다. B의
의미 정확도는 판정 불가이며 제품에 채택하지 않는다. A는 앞선 fact 31건
Trial과 Evidence fingerprint가 달라 출력 수 변화를 개선으로 해석하지 않는다.
이 작은 입력 투영 방식은 timeout 재현 조건·성능 원인을 구별하기 전까지
우선순위를 낮춘다.

015는 별도 Retrieval family다. 현재 RU에는 TASK/CALENDAR_EVENT/FREEBUSY
Source가 있고 frozen Route에도 TASK가 있었지만 Query Planner의 첫 structured
output이 EVENT/FREEBUSY만 내어 TASK/TASK_LIST READ가 생성되지 않았다.
Sufficiency는 title/notes/due/status 부족으로 PARTIAL→Tool Route backedge를
선택했다. 최초 손실은 Query이며 정책 보충을 모든 business Source에 확장하는
근거가 아니다. 이 진단 때문에 준비된 021/023/028 후단 연결을 중단하지 않았다.
