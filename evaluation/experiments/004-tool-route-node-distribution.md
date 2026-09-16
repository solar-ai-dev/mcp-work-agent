# 004. Tool Route 입력 분포와 인접 전달

## 기준·가설·범위

기준 제품 SHA는 `2cf18973`이며 저장 입력은
`canonical92-v8-5a49aa00-ecf32ffc82`다. Request Understanding의
`resource_responsibilities`가 확정되면 Tool Route의 첫 Resource 결정은 대부분
결정 경로로 진행한다는 가설을 검사한다. Source가 틀렸는데 Route만 고쳐 성공으로
세는 오류를 피하기 위해, 저장 Intent의 최신성·의미 정확성과 Route 처리 정확성을
분리한다.

Core 60의 저장된 `WorkflowStartRequest`·`RequestIntent`를 동일 코드의
`requires_io_resource_inference`와 `determine_io_resources`에 직렬 재생한다.
실제 LLM·Connector·WRITE는 실행하지 않는다. `NO_INTENT`와 `LLM_REQUIRED`는
deterministic 성공 분모에 넣지 않는다. LLM 대상이 나오면 대표·반례·기존 성공을
묶어 별도 실제 첫 호출 Node 평가를 준비한다. 전부 결정 경로면 그 계약과 다음
`bind_registry_candidates` 전달을 소수 실제 upstream 결과로 검증하고, Source
정확도를 Route의 성과로 돌리지 않는다. Stress/Holdout은 최종 고정 후보 검증에
남겨둔다.

## 관측·판정

Core 60 저장 checkpoint 중 13건은 `RequestIntent`가 없어 Tool Route 입력 자체가
없었다. 나머지 47건은 모두 `determine_io_resources`의 결정 경로로 반환했고,
LLM 대상 0건·결정 경로 예외 0건이었다. 결정 경로 47건은 Action 32건,
Answer 15건이다. 이는 **주어진 Intent를 Route 후보로 변환한 성공**이지
원문 의미상 업무 성공 47/47이 아니다. 저장 Intent에는 `015`의 Task 누락,
`021/024`의 Task 누락·container 과잉이 있으며, 현재 Request Understanding
재생 결과와도 다르다.

현재 Goal 조립 출력 4건(`014/015/021/028`)을 직접 다음 소비자에 전달한
인접 실험에서는 Source type과 Output pair가 Tool Route 결과에 그대로 나타났고
Route LLM 호출은 0건이었다. 따라서 Source 사실 owner의 누락·과잉이 있다면
Tool Route의 재판단으로 교정되지 않는다. 이는 독립 오류라기보다 계약상
전달 경계이며, Route validator를 느슨하게 하거나 추가 Prompt 규칙을 쓸
근거가 아니다. `024`는 Goal 조립 실패로 이 연결 실험에 들어오지 못했다.

원시 결과: `evaluation/results/tool-route-distribution-core60-20260916/`와
003의 인접 연결 결과. 실제 Tool Route Graph 전체의 policy/registry bind,
confirmation resume, output tool 선택은 이 진단에서 실행하지 않았다.
`LLM_REQUIRED=0`은 이 저장 Core 입력에 국한된다. 다음에는 Retrieval의
Source route→Query→조회→Evidence 구간에서 Task item 누락과 container 과잉의
업무 영향을 검증하고, Scope·확인·follow-up은 별도 적용 입력에서 확인한다.
