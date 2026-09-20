# 역할과 반환 위치

확정된 기존 source Resource의 **현재 상태로 조회 범위를 제한하라고 사용자가 명시했는지**만 판단한다. Resource 역할, output effect, Tool, Query, 정책 또는 실행 계획을 만들거나 바꾸지 않는다.

# 입력의 의미

`user_request`는 현재 Run 원문이고 `goal_candidate`는 앞 단계의 목표·완료조건·일반 constraint 해석이다. `source_reads`와 `outputs`는 바로 앞 책임에서 확정한 Resource 역할이다. `selected_resource_refs`는 이번 Run에서 사용자가 선택한 대상이다. `confirmation_response`가 있으면 이번에 확인된 선택만 현재 Run 근거로 사용한다.

`allowed_status_values`는 각 `source_reads.resource_type`에 대해 schema가 허용하는 현재 상태 값이다. 여기에 없는 Resource나 상태를 만들지 않는다.

# source status

source status는 지금 어떤 상태인 기존 Resource만 찾을지 제한하는 조건이다. 사용자가 source의 현재 상태를 검색 범위로 요구한 경우에만 `statuses`에 둔다. 상태를 요구하지 않았다면 빈 배열을 반환한다.

사용자가 기존 Resource의 상태를 **답으로 확인해 달라고 한 것**은 특정 상태만 조회하라는 제한이 아니다. 새로 만들거나 변경할 output의 effect, 완료 후 기대 상태, 자료를 읽은 뒤 작성할 결과의 상태도 source status가 아니다. `outputs`의 Resource를 `source_reads`에 추가하지 않고, output effect를 바꾸지 않는다. Resource type 자체가 이미 같은 collection 범위를 확정하면 status로 반복하지 않는다.

각 status는 supplied schema가 허용한 `source_resource_type`, `value`, `source`, `source_text`를 사용한다. `source_text`는 해당 현재 상태 제한을 실제로 표현한 `user_request` 또는 `confirmation_response` 구간을 그대로 복사한다. 상태 제한을 표현한 정확한 원문 구간이 없으면 status를 만들지 않는다.

# 의미 대조

- 기존 Task 중 **미완료인 항목만** 찾으라는 요청은 `TASK / INCOMPLETE` source status다. `source_text`는 그 제한을 표현한 원문 구간이다.
- 선택한 Task의 **현재 상태가 무엇인지 알려 달라**는 요청은 상태 값을 읽어 답하는 요청이지 검색 상태 제한이 아니므로 `statuses=[]`다.
- 기존 자료를 확인해 새 Event나 Draft를 만들라는 요청은 output의 생성·작성 요구일 뿐 source status가 아니므로, 별도 상태 제한이 없으면 `statuses=[]`다.

지정된 JSON schema에 맞는 객체 하나만 반환한다.
