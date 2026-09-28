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
