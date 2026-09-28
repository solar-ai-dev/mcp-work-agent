# v30 사전계획: 한 호출에서 현재 업무별 ambiguity owner를 구분

## 원인과 후보 축

v29는 불필요한 collection 질문을 줄였지만, 첫 업무의 selected identity와 다른 업무의
미정 target을 구분하던 성공이 회귀했다. 전역 owner 종류4/6도 구체적인 fact 오류와
업무 귀속을 설명하지 못했다. 다음 후보는 문구 예외를 더하는 대신 **현재 WorkUnit별
owner/missing_fields**를 표현한다. 업무를 재분해하거나 Source/Output/effect를 재판단하지
않으며 기존6개 fixed producer 입력을 사용한다. Work 수는 입력 closed set의 구조 조건이지
새 semantic Gold가 아니다.

- 호출1회. 현재 WorkUnit ID마다 정확히 하나의 `work_ambiguities` 항목.
- 기존 owner enum NONE/USER/CONNECTOR와 missing_fields 의미는 그대로.
- 원문·selected refs·확정 Work/Source/Output/조건·현재 confirmation은 그대로 복사.
- 입력의 `searchable_target_anchor_count`와 `connector_owned_source_count`만 제거.
- Prompt는 v29 삭제 후 내용을 기반으로 업무별 책임·출력 형상 설명만 정합화하고,
  더 이상 입력에 없는 두 count의 설명을 제거한다. 예제·lexical rule 추가0.
- unknown/duplicate/missing Work ID는 구조 오류. 업무별 owner가 NONE이면 fields는 비고,
  USER/CONNECTOR이면 비지 않아야 한다는 기존 불변조건도 유지한다.

## Typed 결과 → 현재 Product replay

`raw work_ambiguities → deterministic fold → 현재 detect_ambiguity validator → AmbiguityV1`

fold는 USER 항목이 있으면 해당 USER fields만, 아니면 CONNECTOR fields만, 아니면 NONE을
선택한다. field 문자열은 변경하지 않으며 같은 문자열이 서로 다른 업무에 있더라도
조용히 합치지 않는다. 낮은 우선순위의 잘못된 항목을 fold로 숨기지 않는다.
Schema와 현재 Product의 출력 불변식 이외에 업무 의미를 코드가 고치지 않는다.

현재 Product projector에는 원래 count가 남아 있으므로 schema 조립용 Product base와
후보 실제 wire input을 분리해 검증한다. Candidate system JSON와 transport input 모두
같은 count-free projection을 받는다. repair도 같은 입력과 work-bound schema를 재사용한다.
Product postvalidator replay는 모델 호출 없이 원래 Product projection에서 수행한다.

원시 업무별 결과, fold, 현재 postvalidator 결과를 모두 따로 기록한다. 지금의 persisted
AmbiguityV1에는 WorkUnit 귀속 필드가 없으므로 fold 후 same-Work confirmation resume까지
완결됐다고 하지 않는다. 본 후보는 Product migration이 아니라 owner 표현 진단이다.

## 고정 비교와 baseline 재사용

v29와 같은6개: anchor-first/other-target, selected-first/other-target, CRITERIA 전체목록,
pure CREATE, 실제 과거 CORE005/019 producer. Gold·새 계정 정보는 모델에 넣지 않는다.
CORE019의 잘못된 Draft/Calendar upstream Source와 CORE005 opaque 선택 ref도 보존한다.

v29 **Product baseline6개만** 원래 raw에서 재사용한다. v29 후보 응답은 대체 baseline으로
쓰지 않는다. 실제 input/Schema/assembled Prompt hash, 모델 digest, sampler/runtime,
dataset/fixture hash, 관련 Product/관측 코드 hash와 현재 postvalidator 결과가 같아야 한다.
공통 manifest/input-contract JSON에 다른 Node slot만 변경된 경우에는 과거 HEAD의 원본
파일 hash가 기록과 일치하는지 확인한 뒤 전역 metadata와 ambiguity slot을 exact 비교한다.
관련 slot·전역 금지·실제 consumer 코드가 바뀌면 재사용을 거절한다.

신규 candidate6 FIRST, 각 schema repair최대1, semantic revision0, transport retry0,
rerun-to-pass0. 등록 후 입력·코드·HEAD 변경 또는 기존 raw 덮어쓰기를 허용하지 않는다.
qwen3.5:9b 실제 installed digest, temperature0/seed20260923/ctx16384/thinkfalse/timeout180.
재사용과 신규 calls/tokens/latency는 분리한다. usage 누락을0으로 채운 성공 기록은 만들지 않는다.

```powershell
.venv/Scripts/python.exe -m scripts.evaluate_ambiguity_owner --comparison product-v30 --reuse-baseline-raw evaluation/results/064-ambiguity-owner-v29-t1/raw.json --result-dir evaluation/results/064-ambiguity-work-bound-v30-t1
.venv/Scripts/python.exe -m scripts.evaluate_ambiguity_owner --result-dir evaluation/results/064-ambiguity-work-bound-v30-t1 --execute-plan evaluation/results/064-ambiguity-work-bound-v30-t1/preregistered-plan.json --expected-plan-sha256 <등록 hash>
```

## 판정과 제한

업무1의 target이 확정돼도 업무2의 target은 미정인 반례를 각각 검사한다. USER라는
전역 fold가 맞아도 실제로 USER를 잘못된 업무1에 귀속했다면 성공이 아니다.
collection에서 owner 종류만 CONNECTOR여도 내부 metadata나 요청 문장을 fact로 출력하면
의미 성공으로 집계하지 않는다. CORE019는 관련 READ 후 시간 확인을 허용하되 upstream
오염을 감추거나 전체 업무 PASS로 세지 않는다. 구조, owner 종류, 업무별 실제 선택/조회 사실,
fold 이후 결과와 기존 성공 회귀를 별도로 검수한다.

준비 단계는 direct/fake transport 검증만 수행한다. 실제 모델 실행은 Root의 사전등록 이후다.
Product/Prompt activation/Node/State migration0, Provider READ/WRITE0.

## 실제 결과 — 구조 유효성으로 의미 실패를 가리지 않음

실행 HEAD `0ee84dba`, plan SHA256
`44c88ecc607b258d3ba3674a75e5ed6afd0b78b521f1b05b5b6633294f55a5e9`.
기존 Product baseline6개를 검증 후 재사용했고 후보6개를 각1회 실행했다.
후보 FIRST schema6/6, repair0, semantic revision0, rerun0이다. 업무별 ID는 모두
closed set과 일치했으나 이것이 업무별 판단의 정확성을 보장하지 않았다.

| 입력 | Product baseline | v30 FIRST → fold/후처리 | 판단 |
| --- | --- | --- | --- |
| Alpha 일정 + 별도 미정 일정 | 전역 CONNECTOR | 두 Work 모두 CONNECTOR/event_identity → 확인 없음 | 다른 업무의 target이 미정인데 identity를 조회할 속성으로 취급. 최초 손실은 Work2의 LLM 판단이며 fold가 아님 |
| 선택 일정 + 별도 미정 일정 | USER/target_resource | 두 Work 모두 NONE → 확인 없음 | 기존 성공 회귀. Work2의 필요한 사용자 선택이 사라짐. NONE을 READ 불필요와 동일시하지는 않으나, 대상 미정의 확인 누락은 남음 |
| 작업 collection 전체 제목/상태 | USER/target_resource | CONNECTOR/title,completion_status → 확인 없음 | 불필요 질문 감소와 조회 fact 표현 모두 개선. v29의 count-as-fact 오류는 재발하지 않음 |
| 지정 목록 Task CREATE | NONE | NONE | 기존 owner 성공 유지; 실제 승인/생성은 미실행 |
| CORE005 선택 Task 조회 | CONNECTOR | 동일 Source facts의 CONNECTOR | 기존 owner 성공 유지; 실제 답변 정확도는 이번 범위 밖 |
| CORE019 | CONNECTOR | 기존 Source facts의 CONNECTOR | 관련 READ 진행 허용 범위 유지. 원래 Source 오판은 그대로이며 전체 업무 성공으로 세지 않음 |

전역 owner 종류만은4/6→4/6이다. collection은 의미 개선이지만 selected-other 회귀가
있으므로 **Production 미채택**이다. typed per-Work 결과를 표현·전달할 수 있다는 것과
모델이 실제 사용자 선택/조회 사실을 구분했다는 것을 분리한다. validator나 fold가
정상 USER를 지운 사례는 없으며 FIRST 단계에서 이미 USER가 생성되지 않았다.

신규6 calls/input15,833/output436 tokens/reported30,300ms/usage누락0.
재사용 baseline6 calls/input17,403/output98/reported20,384ms는 새 실행 비용에 더하지 않는다.
표현량과 응답 tokens는 증가했고 지연 개선 근거도 없다. 반복 안정성·fresh upstream·
same-Run confirmation binding·Retrieval/Planning 이후는 미검증이다.

추가 enum/설명/예제를 붙여 같은 표현 실험을 반복하지 않는다. 실제 selected Source ref
귀속과 target 선택 책임의 연결, 이미 확인된 소비 경계 결함 및 compiled workflow 연결을
다음 조사 대상으로 유지한다. 후보 판정만으로 전체 작업을 종료하지 않는다.

raw: `evaluation/results/064-ambiguity-work-bound-v30-t1/raw.json`, SHA256
`c4894fbe93caea6012224fc7b3808f47dff17e5c4abeeb4e49991bb8ff22168d`.
Provider READ/WRITE0, Product activation0. 원본 raw 불변.

## 테스트 지원 경계 정리와 architecture 재확인

v29/v30의 fake Ollama transport를 `tests/support/ollama_transport.py`로 옮겨
테스트 간 private helper import를 제거했다. queued 응답, wire 기록과 usage 값은
동일하며 직접 테스트30/30, 해당 파일 Ruff 검사는 통과했다. Product/candidate/
runner/raw 변경과 모델/Provider 호출은 없다.
Root 재검토에서 이번 v30 테스트의 중첩 fixture에 명시 타입을 추가하여 타입 추론 오류도
교정했다. 공용 helper와 두 테스트 파일의 scoped Mypy3개 파일 및 직접30개 테스트가 통과했다.

별도 실행한 evaluation architecture 검사2건은 여전히 실패한다. 시작 SHA
`4f07c3b5`와 비교한 비허용 evaluation Python 파일15개 및 내부 Product import25개는
정확히 동일하며 이번 후보의 신규 회귀가 아니다. Product→evaluation/scripts/candidate
직접 import는 정적 검사0이다. Canonical12/13의 개발 Graph/Node 진단 허용과
Canonical16의 공식 evaluation 내부 import 금지는 구분한다. 기존 위반을 통과시키기
위해 테스트/allowlist를 변경하거나 정리 범위를 확대하지 않았다.
