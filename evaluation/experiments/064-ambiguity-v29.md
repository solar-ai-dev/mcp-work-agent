# v29: count shortcut를 제거한 ambiguity owner 단발 비교

## 가설과 변경 범위

`cb0fe481`의 입력 carry와 multi-Work 소비 guard는 현재 Product에 유지한다.
기존 Prompt는 Source/anchor의 **전역 개수**만으로 `USER`/`CONNECTOR`를 강제한다.
이 방식은 한 업무만 검색 가능한 multi-Work와 검색어 없는 `CRITERIA` collection을
구분할 수 없다. 새 예외 규칙이 아니라 판단 2/3, 반복 문단, 구조 예시를 제거한
evaluation-only 후보를 비교한다. 나머지 원문·확정 업무/Source·선택 대상·현재 확인 응답의
소비 책임과 출력 계약은 그대로 둔다. 입력·Schema·Node·validator는 양쪽이 같다.

Product Prompt/manifest/활성화와 Approval·Provider 경계는 변경하지 않는다.
Schema repair는 기존 bounded failure projection과 기존 scope guard를 그대로 사용한다.
semantic validator 실패에는 재호출하지 않는다.

## 사전 고정 6개

| 입력 | 확인할 업무 의미 |
| --- | --- |
| 두 업무 중 첫 일정만 Alpha anchor가 있음 | 첫 anchor가 다른 미지정 대상의 사용자 선택을 지우지 않음 |
| 첫 일정 하나가 선택됨, 다른 업무 일정 미정 | 동일 Resource 종류의 선택 하나로 전체 대상 해결하지 않음 |
| 검색어 없이 작업 collection 전체 제목/상태 조회 | `CRITERIA` 범위가 명확하면 keyword 부재 자체로 target 질문하지 않음 |
| 명시된 작업 목록에 새 Task 생성, 기존 Source 없음 | 새 Task identity를 다시 묻지 않으며 생성은 여전히 승인 후 |
| CORE-005 실제 과거 producer | 선택 Task의 상태/기한은 조회할 사실, 새 사용자 선택 아님 |
| CORE-019 실제 v4 producer | 관련 READ 후 시간 확인 또는 구체적 시간 확인을 허용 |

앞 4개는 명시적인 typed owner fixture다. 실제 모델의 upstream 성공이라고 하지 않는다.
pure CREATE fixture는 단일 인증 시험 계정 및 지정 작업 목록 접근 권한을 전제로 한다.
이 환경 가정이나 Gold는 모델 입력에 추가하지 않는다.

Core 원문은 현재 Canonical v8과 exact 일치하는지 확인한다. 과거 actual ambiguity input의
Goal/조건/Output/selected identity를 보존하고, 당시 앞단 actual input에 존재했던
requested_work와 source work_unit_ids만 현재 Product projection으로 carry한다.
Source resource/facts/target_scope가 당시 ambiguity input과 일치해야만 복원한다.
새 Goal·Source·업무 귀속을 생성하지 않는다. `requested_*_hints`만 기존 canonical
derivation으로 구성하며 해당 hints는 ambiguity Prompt에 투영되지 않는다.

CORE-019의 과거 `GMAIL_DRAFT` 및 `CALENDAR` Source 오판은 그대로 남긴다.
이 owner 비교가 그 upstream 오류를 고쳤다는 뜻이 아니다. CORE-005의 과거 opaque
`resource_ref_id`에 Case ID가 포함된 점도 양쪽에서 동일하게 보존한다.

재사용 입력 원본 SHA·파일 hash·세부 producer input hash는
`064-ambiguity-v29-frozen-inputs.json`에 기록한다. 기존 ambiguity 응답은 재사용하지 않는다.

## 실행 계약

- 고정 6개 × baseline/candidate 각 1회 = FIRST 최대 12회.
- schema repair 각 최대 1회, semantic revision/transport retry/rerun-to-pass 0.
- 실제 installed qwen3.5:9b digest와 실행 HEAD/코드/입력/Schema/Prompt hash 사전 결속.
- 실제 ambiguity 온도 0.0, 평가 seed 20260923, context 16384, think=false, timeout 180초.
- seed는 평가 설정이지 전역 Product 기본값이라고 주장하지 않는다.
- Root가 실행하며 이 후보 준비 단계의 실제 모델/Provider 호출은 0.

```powershell
.venv/Scripts/python.exe -m scripts.evaluate_ambiguity_owner --result-dir evaluation/results/064-ambiguity-owner-v29-t1
.venv/Scripts/python.exe -m scripts.evaluate_ambiguity_owner --result-dir evaluation/results/064-ambiguity-owner-v29-t1 --execute-plan evaluation/results/064-ambiguity-owner-v29-t1/preregistered-plan.json --expected-plan-sha256 <첫 명령이 출력한 hash>
```

기존 raw가 있으면 덮어쓰거나 이어서 다시 돌리지 않는다. 준비 후 HEAD/코드/입력/정책이
바뀌면 실행을 거절한다. input/output usage 누락은 `missing_usage_calls`로 남긴다.

## 판정과 미검증

FIRST raw → schema repair raw → 현재 Product postvalidator 결과를 각각 보존한다.
`OWNER_CHOICE_PASS`는 owner 종류만 맞았다는 좁은 기계 판정이다. missing_fields가 실제
사용자 선택인지/불필요한 질문인지 원문과 함께 수동 검수하기 전 semantic PASS로 세지 않는다.
CORE-019의 구체적 시간 질문과 잘못된 target/수신자 질문을 같은 USER 성공으로 집계하지 않는다.
단일 Work의 기존 deterministic 정규화가 FIRST 판단을 바꾸면 별도 divergence로 기록한다.
업무 개수나 missing_fields 문자열 한 형태를 Gold로 강제하지 않는다.

직접 fake transport 테스트는 모델 품질 결과가 아니다. Owner 성공도 전체 RU나
Tool Route/실제 Retrieval/Planning/최종 업무 성공을 증명하지 않는다.

## 실제 단발 결과와 의미 검수

실행 HEAD `180dcdfdcc383a51b5811f53f73b72c5a2ac5806`, plan SHA256
`24691348fbec1d596a927aed2fc2fb3cbf59d409bb7d91f581d12f769c948207`.
사전 고정한 6개를 baseline/candidate 각1회, 총12 FIRST calls 실행했다.
양쪽 첫 schema6/6, repair0, semantic revision0, rerun0이다.
raw의 owner 종류만 보는 기계 판정은 **4/6→4/6**이지만 동등한 의미 결과가 아니다.

| 요청·경계 | baseline FIRST → postvalidator | 후보 FIRST → postvalidator | 원문 기준 의미 검수 |
| --- | --- | --- | --- |
| Alpha 일정 시작 + 별도 미정 일정 종료 | CONNECTOR / target_resource → 확인 없음 | CONNECTOR / 두 업무의 시간 조회 → 확인 없음 | 양쪽 실패. Alpha 검색 anchor는 첫 업무에만 있는데 다른 업무의 대상까지 조회 가능하다고 판단. 최초 손실은 LLM owner 출력이며 현재 validator가 USER를 덮어쓴 결과가 아님 |
| 선택한 일정 시작 + 별도 미정 일정 종료 | USER / target_resource → 확인 필요 | CONNECTOR / 두 업무의 요청 문장 → 확인 없음 | **기존 성공 회귀.** 첫 선택 identity가 없는 두 번째 업무를 해결하지 못한다. 후보는 별도 target 선택과 그 target 속성 조회를 구분하지 못했고 missing_fields에는 조회할 fact 대신 요청 문장도 복사함 |
| 작업 collection 전체 제목/상태 | USER / target_resource → 불필요 확인 | CONNECTOR / searchable_target_anchor_count → 확인 없음 | 불필요 target 질문을 없앤 방향은 개선. 다만 count라는 입력 metadata를 Connector가 조회할 사실로 잘못 출력하여 의미 완전 통과는 아님 |
| 지정 목록의 새 Task 생성 | NONE / 빈 배열 → 확인 없음 | 동일 | 이 owner control은 유지. 새 Task identity를 요구하지 않음. 실제 생성·승인 실행은 하지 않음 |
| CORE005 선택 Task 상태/기한 | CONNECTOR / due·completion_status 등 기존 Source facts → 확인 없음 | 동일 | 선택 대상의 속성을 사용자에게 다시 묻지 않음. 기존 Source가 요청보다 넓게 보유한 title/notes 등의 facts도 동일하며 이 실험이 이를 새로 정한 것은 아님 |
| CORE019 일정 및 안내 초안 | CONNECTOR / event_identity → 확인 없음 | CONNECTOR / 기존 Draft와 Calendar Source의 전체 fact 목록 → 확인 없음 | 관련 READ 후 필요한 시간 확인을 허용하는 owner 진행 방향은 양쪽 허용 가능. 원래 잘못된 GMAIL_DRAFT/CALENDAR 입력을 보존했으므로 조회 자체의 업무 적절성이나 최종 시간 확인 성공은 증명하지 못함 |

collection 후보의 `searchable_target_anchor_count`는 실제 Provider fact가 아니다.
현재 schema가 string 형태를 허용하므로 구조 통과했지만 자연어 의미가 맞다는 뜻은 아니다.
postvalidator의 CONNECTOR 경로는 이 missing_fields를 persisted ambiguity에 남기지 않고
`requires_confirmation=false`, `missing_fields=[]`로 정규화한다. 따라서 이 raw 오류가
실제 Provider query나 사용자 질문으로 실행됐다고 주장하지 않는다. 동일하게 CORE019의
긴 facts 목록도 Source owner가 이미 확정한 값을 복사한 관측이지 새로운 성공 근거가 아니다.

Product의 새 multi-Work guard는 baseline의 selected-other USER를 그대로 보존했다.
후보에서 USER가 사라진 이유는 guard가 아니며, FIRST 자체가 CONNECTOR로 판단했다.
이 실험에는 repair나 semantic revision이 없으므로 최초 출력과 후처리의 원인 경계가
명확하다. 신규 count 예외나 validator의 의미 덮어쓰기로 이 차이를 보정하지 않았다.

### 비용

| arm | calls | input / output tokens | reported latency | usage 누락 |
| --- | ---: | ---: | ---: | ---: |
| baseline | 6 | 17,403 / 98 | 20,384ms | 0 |
| 후보 | 6 | 15,129 / 158 | 15,523ms | 0 |

문구 삭제로 input은2,274 tokens 감소했지만 output은60 tokens 증가했다.
총 reported latency는4,861ms 감소했다. 다만 첫 pair의 시간 차이5,273ms가 전체 차이보다
크고 나머지5개 합계는 후보가412ms 느렸다. 고정 baseline→candidate 순서의 단발이며
cache/워밍업 영향을 분리하지 않았으므로 반복 성능 향상이나 전체 Run 지연 개선으로
일반화하지 않는다. 실제 temperature0/seed20260923/ctx16384/thinkfalse/timeout180,
model digest는 사전등록과 같다.

### 판단과 다음 축

**현재 후보는 Production 미채택.** 전역 count 규칙 삭제는 CRITERIA의 잘못된 질문을
줄였으나, multi-Work 대상 구별을 안정화하지 못했고 기존 성공을 회귀시켰다.
owner 종류만4/6으로 같다는 이유로 동률·개선 완료라고 판정하지 않는다. collection의
wrong fact와 CORE019의 오염된 upstream 때문에 기계 점수를 완전 의미 PASS로 승계하지 않는다.

동일 방향의 Prompt 삭제/예외 문구 추가를 연속 시도하지 않는다. 다음 검토 축은 기존
WorkUnit·Source item의 target_scope·선택 identity를 연결한 **대상/조회 책임 binding**이다.
현재 하나의 전역 owner와 귀속 없는 missing_fields가 서로 다른 업무의 선택 필요와
조회 가능한 사실을 혼합하는지, 실제 source-item/work binding을 소비·반환하는 표현으로
구분 가능한지를 먼저 확인한다. confirmed Source나 selected identity를 코드가 임의의
업무에 붙이거나 CRITERIA에 무조건 CONNECTOR를 강제하는 새 규칙은 근거가 아니다.
별도의 상태/출력 계약이 필요하면 evaluation-only로 검토하며 이 결과만으로 Product에
넣지 않는다. 승인·권한·실행 안전 경계는 변경하지 않는다.

원본: `evaluation/results/064-ambiguity-owner-v29-t1/raw.json`, SHA256
`9f5990393622db72e8bf7b228ed3fd092439a8c1b5e3ff5f602fc805cf7b2748`.
raw는 그대로 보존했다. Provider READ/WRITE0, Product Prompt/activation 변경0.
현재 결과는 고정 upstream의 ambiguity owner 진단이며 전체 RU·Tool Route·Retrieval·Planning
업무 성공률, 실제 Connector 진행 또는 최종 사용자 확인 성공은 미검증이다.
