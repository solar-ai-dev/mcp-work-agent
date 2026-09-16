# 029. 채택 SHA의 대표 백엔드 Run·LangSmith 확인

제품 기준 `d59b69d124845967c49e10a87fc4af7757f98fae`, pushed branch
`codex/issue-251-connected-contract`. 028의 compiled 수정 순환과 별도로
격리 `runtime/review-resolution-live-d59b69d1`에서 기존
`scripts.serve_canonical_v8_product` 백엔드를 1회 새로 시작했다.
기존 백엔드 listener/활성 Domain Run은 0, 모델 서버는 재사용했다.
백엔드 교체·재시작 0, bootstrap 1회 성공, 공식 Domain Run 1개,
사전 진단 Domain Run 1개, 공식 Case rerun 0. 무거운 호출은 직렬.
합성 Stateful Provider fixture만 연결했고 실제 계정 WRITE는 허용하지
않았다. 두 Run 모두 `auto_approve=False`였으며 Connector WRITE 관측 0.
종료 시 활성 Run은 없었고 자체 백엔드는 제품 shutdown API로 정상
종료했다. 데이터베이스·로컬 결과는 보존했다.

LangSmith CLI를 먼저 시도했으나 설치된 `langsmith.exe`가 `trace`
하위 명령을 제공하지 않는 이전 실행 파일이었다. 저장소에서도 쓰는
Python LangSmith SDK로 원격 project
`google-work-agent-review-d59b69d1`을 조회했다. 로컬 trace ID만
가지고 성공 처리하지 않았다. root metadata의 code SHA는 위 SHA,
Prompt manifest SHA-256은
`5fe588caec9870c0854ac992ba2888b75a0db360f015a619215fb0e695b1dd6d`,
모델 digest는 021/028과 동일한
`6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`.
원문·전체 State·Secret은 원격 조회 결과나 버전관리 기록에 복사하지
않았다.

| 단계 | Domain Run | 원격 Trace root | 관측 |
| --- | --- | --- | --- |
| 사전 READ-only Kestrel 진단 | `1da9b6a4-feb7-4c92-8262-988d8c05205f` | `01a0ac70-1ea8-7433-b907-ac669cbc9390` | root+하위 Node+LLM 12 확인. `compose_arguments_per_output_route` 경계에서 `CONTRACT_VIOLATION`, `RECOVERY_REQUIRED`. 실패 보존, 재시도 없음. |
| 대표 023 최초 Preview | `ca7e3aad-6412-40d3-83df-23b0af71126d` | `01a0ac72-91be-7163-8bba-940b8c27a10a` | 79 trace runs/LLM 21, 초기 Review 3호출, Plan revision 1, Action 1개 `PROPOSED`, `WAITING_APPROVAL`. 승인·WRITE 0. |
| 같은 Run의 허용 제목 Preview 수정 후 resume | 위 Domain Run 동일 | `01a0ac78-1209-7453-b449-e5e3644ea619`, `01a0ac78-1238-7b20-9f16-1a64c1e72676`, `01a0ac78-1279-74f1-ba48-483ac9472881` | `ModifyAction` applied, Action `MODIFIED`, 이전 Plan `SUPERSEDED` → `RETRIEVING` → 초기 Review 재실행 → `BLOCKED`. 마지막 root의 LLM 5. 승인·WRITE 0. |

동일 백엔드의 첫 Run에서 root/child/LLM 원격 기록을 확인한 후 대표
023을 제출했다. 사전 Run 실패는 공식 023 결과로 대체하지 않는다.
대표 Run의 정상 초기 Review는 새 `recheck_affected_dimensions`를
호출하지 않았다. Preview 수정 resume도 RECHECK가 아니라 초기 Review를
다시 실행하고 BLOCKED였다. 따라서 Live는 새 코드 SHA의 로딩·저장·
재진입·추적 경계를 확인했지만 **028의 수정 순환 의미 성공을 Live에서
증명하지는 않는다**. 028의 두 오류 유형 성공은 고정 입력 compiled
Review→Planning→RECHECK 검증으로만 주장한다.

잔여 공통 실패: 현재 사용자 Preview 수정이 초기 Review에서 이전
제약과 충돌한 것처럼 처리되는 경계, 실제 외부 메일 근거 부족을
확인 질문으로 보내는 경계. 또한 사전 READ-only Run의 Planning
argument contract 실패는 이번 변경과 별도다. Live 수정 후 BLOCKED의
구체적 finding 의미는 이 검사에서 raw State/Prompt를 외부로 옮겨
확정하지 않았으므로 추가 원인 단정은 보류한다. `review.recheck`의
confirmation/no-transition 경로, 실제 Provider READ 효과, 전체 92,
승인 후 Verification은 미검증이다. 다음 사이클은 초기 Review의
현재 수정 권위와 Evidence 부족 분류를 동일 Node 다중 입력으로
비교해야 하며 이번 RECHECK PASS로 덮지 않는다.
