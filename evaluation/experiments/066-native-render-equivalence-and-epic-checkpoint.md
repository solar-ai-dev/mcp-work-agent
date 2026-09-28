# 066 — Native render 동등성 / #286 현재 근거의 경계

## #303 무생성 확인

HEAD `58b1875c8a574172a411696a342d1b0c846f7015`, Ollama0.34.0,
qwen3.5:9b digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`.
Source009/049/059의 이미 고정한 **original 9B payload**를 재사용했다. v45 ablation이나
v46의4B candidate payload를 사용하지 않았다. 세 요청 각각 generate/chat에
`_debug_render_only=true`를 넣어 총6회 직렬 관측했다. generation0, Provider0.

chat에서는 `system/prompt`만 같은 문자열의 system/user messages로 바꾸고
format, think=false, stream=false, num_ctx16384, temperature0.05, seed20260923를 보존했다.
새 모델/Prompt/Schema 후보가 아니라 실제 role 조립의 read-only 진단이다.

| Core | generate = chat SHA256 | UTF-8 bytes |
| --- | --- | ---: |
| 009 | `d0a9238c9589587768d1f503ccbc816cd6b768b30606ac0884d8a7595db98e5f` | 16,744 |
| 049 | `47e1a5956d3afb593bca04f8f893454b083eb952ef93c33023cacb2d590d41e1` | 18,643 |
| 059 | `23f6d33d43aeb79127a2b7188edb39e229a3931a17cd498708885af451009b37` | 16,659 |

6개 응답 모두 debug render 존재, done=false, 생성 content와 usage count 없음.
**실제 렌더 byte 동일3/3**이며 system/user/assistant 및 think=false 닫힘 구간이 존재한다.
최초 예상 문자열 비교는 system 끝 공백1자를 그대로 두어 false였다. 실제 source를 보고
native edge trim을 반영한 예상 문자열 hash를 오프라인으로 계산하니 관측 hash3개와 모두
일치했다. 사용자 JSON 문자열 내부/원문은 변경되지 않았다. 확인을 위한 추가 호출0.

이 edge trim과 debug-only 조기 반환은 버전 고정 공식
[renderer](https://github.com/ollama/ollama/blob/v0.34.0/model/renderers/qwen35.go) 및
[server](https://github.com/ollama/ollama/blob/v0.34.0/server/routes.go)에서도 확인된다.
**render 동등성은 completion/parser/structured-output 동작 전체의 동등성 증명이 아니다.**
다만 현재 Source 실패를 'generate가 system을 누락한다' 또는 'chat으로 바꾸면 역할이
복구된다'고 설명할 근거는 없다. 같은 내용으로 endpoint-only model trial을 추가하지 않는다.

안전 projection은 `evaluation/results/066-native-render-equivalence/observation.json`.
파일 SHA256은 `712c31c61ec558272b64acd9e2e719e8bb6774c879f35c9867d9945fdd4cb493`.
입력 source plan 파일 hash는 `c0f2834dfdf87ff6bd7ef79eda62e2561518e3b20b231d66ff642c5ee7954497`.
시각은 2026-09-28T16:18:21Z(한국9월29일). 시작 시 model 미상주/RAM여유19.66GiB,
GPU0/8188MiB·41°C. render도 model load를 일으킬 수 있으며 'GPU 사용0'이라고 하지 않는다.
서버 재시작·개인 process 종료·설정 변경0. 상세 원문을 commit하지 않는다.

## 이번 구간의 판단과 비교 범위

시작HEAD `621d4468841ab77bac88e5c08a0c30b63f5e8862` 이후 #287→#290→#296→#303을
확인했다. 각각의 서로 다른 분모/실행시점 결과를 합쳐 전체 성공률로 만들지 않는다.

| 범위 | 결과 | 판단 |
| --- | --- | --- |
| v45 Source metadata 제거, 신규3 FIRST | 기존1 PASS/1 PARTIAL/1 FAIL → 동일합계, 성공·실패 Case 교환 | REJECT. CORE009 개선 대신049/059 회귀 |
| 현재 Production CORE005 MainGraph T3,1회 | FAIL/BLOCKED, LLM9회, snapshot READ0 | 미요청 UPDATE/SEND와 invalid query-ref를 별도 owner로 확인 |
| exact-ref generation Schema 계약 | 새14 직접검사 PASS, 관련기존1,698 PASS | `b7c449fa` Product 채택. validator와 같은 허용 ref를 생성 Schema에 결속 |
| v46 fixed4B Source, 신규3 FIRST | 기존1/1/1 → 0/0/3 | REJECT. 필요한 Source 전부 제외; 구조3/3 통과와 의미실패를 구분 |
| generate/chat render-only | byte 동일3/3, 생성0 | endpoint 변경의 의미 개선 근거 없음 |

새 모델 생성 총15회(3+9+3), 입력53,937/출력2,282 tokens,
각 API 보고 지연 합123,145ms. 다른 책임/모델의 실행량 합계일 뿐 전후 속도효과가 아니다.
누락usage0, 재실행-to-pass0, Live Provider READ/WRITE0, 승인0.
주요 원 결과와 자세한 비용은 `066-source-catalog-projection-v45-result.md`,
`066-production-core005-t3-and-query-ref-binding.md`,
`066-source-fixed-model-v46-result.md`에 분리 보존했다.

Query 수정은 첫/revision Schema에 기존 `allowed_resource_refs ∪ detail_candidate_refs`를
반영한 것이다. ID 추정·validator 완화·예산 증가·Prompt patch가 아니다.
Product Prompt/State/Node/Approval/Execution 의미는 변경하지 않았다.
수정 뒤 실제 모델/MainGraph 재검증을 했다고 주장하지 않는다.

## 왜 다음 작은 RU 변형을 바로 추가하지 않는가

기존 기록과 raw를 독립 검토해도 현재 남은 Source 누락/Output 오판의 FIRST가
deterministic 조립에서 바뀐 것이 아니라 모델에서 이미 생성됐음을 확인했다.
T3에서는 Goal의 실행값 슬롯 오염도 FIRST에 있지만 이것이 Output 오판의 원인이라는
인과 증거는 없다. validator가 이 의미를 대신 만들어 정상으로 바꾸면 안 된다.

| 실패군 | 이미 검증한 일반 축 | 남은 근거 제한 |
| --- | --- | --- |
| Source 누락/과선택 | 003 constraints 제거·sparse,063 needs/ref·two-stage·fusion·map·중복Schema,064 family/membership·format·간결화·sampling·contrastive,066 Tool metadata 제거·4B | 실패 위치 교환 또는 기존 성공 회귀. 같은 방법의 문구 변형을 새로운 원인 해결로 부를 수 없음 |
| 미요청 Output WRITE | 044 Goal 제거/bounded/Resource별/gate/provenance/span,062~064 공동 authority·format | v4의 Output 재생성 제거는 유효한 아이디어지만 Goal completion·Source·금지·status 회귀가 닫히지 않음 |
| Goal 실행값 오염 | 기존 span/provenance/owner projection 비교와 T3 FIRST | 원문에 있는 문자열이라는 사실만으로 실행값임을 증명하지 못함. 새 origin label만으로 해결된다고 가정 불가 |
| Runtime 역할 누락 가설 | native model config/sentinel 및 이번 full payload render | 현재 system/user 실제 보존 확인. endpoint 명칭만 바꾼 재시도 근거 없음 |

현재 근거로는 다음 Prompt/Schema/Node 작은 변형의 반증 가능한 새 인과 가설이 부족하다.
따라서 사용자 종료 조건4(추가 시도가 근거 없는 random search가 되는 경계)에 도달한 것으로
기록하고 **추측성 새 모델 호출은 추가하지 않는다**. 이는 '9B의 한계 확정', '가능한 모든
해법 소진', '#286 완료' 또는 SFT 필요성의 증명이 아니다. 증거를 갖춘 다른 축은 재개할 수 있다.

재개 조건은 실제 runtime/render/parse 불일치, 현재와 다른 책임/입력 경계에서의 측정된
인과 근거, 또는 사전 검증 가능한 독립 모델/학습 계획이다. 이미 실패한 방법의 이름이나
문구만 바꾸는 것은 재개 조건이 아니다. 새 모델 download/training을 임의로 시작하지 않는다.

## 미완료를 명시

- #286 **미완료**. 최신 고정 Product SHA의 Canonical92 전체 성공률은 이번에 측정하지 않았다.
  과거061/062 점수를 현재 Product 점수로 승계하지 않는다.
- Source/Output/Goal의 의미 실패가 남는다. Work/item binding 보존과 업무 성공은 다르다.
- CORE005 연결 실패를 PASS로 바꾸지 않았고, Query fix 뒤 업무 성공도 미검증이다.
- Retrieval→WorkAnalysis→Planning→Review→승인 후 Execution/Verification 전체 안정성,
  Live Provider 업무 성공, Release activation은 검증되지 않았다. 안전 gate는 유지한다.
- Source-only 후보에서 불필요 WRITE가0이었다고 추정하지 않는다. 해당 owner를 실행하지 않았다.

완료 상태나 Issue 본문은 변경하지 않는다. commit/push·결과 댓글은 검토 가능한 근거 보존이며
그 자체를 전체 안정화의 완료 근거로 삼지 않는다.
