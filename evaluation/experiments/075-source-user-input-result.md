# 075 — USER-only 입력 배치: 두 arm 모두 REJECT

실행 SHA `d35e257f5e485cf3ffa92e520357ed2d2ad5f5dc`. Source FIRST6회,
repair/retry0, 시작·종료binding동일. strict검증6/6, raw→validator→source-only merge
의미 변경0이다. 오류는 모두 Source 첫 생성에서 발생했다.

| Core | plain USER-only | 해석 포함 USER-only |
| --- | --- | --- |
| 017 | PARTIAL: Task/Event유지, 기존Draft필수조회오인유지 | PARTIAL:074에서사라졌던기존Draft조회다시추가 |
| 049 | FAIL:Task/Event유지, 필요한메일정보를새Draft수신자주소하나로대체 | PARTIAL:메일내역/Task/Event복구, 불필요기존Draft조회남음 |
| 005 | PASS:선택Task상태/기한과단일대상유지 | PASS:동일필요의미유지 |

- plain: historical v42 **1P/2PART/0F → 1P/1PART/1F**.
- interpreted:074 **2P/0PART/1F → 1P/2PART/0F**.017기존성공회귀.
- 두 arm 중 Case마다좋은응답만골라성공률을만들지않았다. 독립검수동일.

plain049의실패는Message를선택하지않아서가아니다. Thread를통한메일조회는정상대안이다.
문제는 required_information을 이미사용자가제공한새Draft수신자주소로대체해
기존Atlas메일의업무정보를요구하지않는것이다. interpreted049의Message에붙은
message_history는표현차이만으로실패강요하지않았다. Freebusy보조조회도개수만으로
실패처리하지않고, 기존Draft를필수화하는오류를PARTIAL근거로삼았다.

## 고정조건·비용

전체USER input·Schema·PromptRef·format·sampling불변. SYSTEM의정확한중복입력
JSON과제목만제거했다. v22SYSTEM-only와반대방향이며새로운의미규칙은없다.
qwen3.5:9b 기존digest/Ollama0.34.0/temp0.05/seed20260923/ctx16384/think=false,
presenceoverride없음. Source role및공통instruction은그대로다.

| arm | 신규calls | input/output tokens | reported latency |
| --- | ---: | ---: | ---: |
| plain | 3 | 10,321 / 785 | 39,974ms |
| interpreted Source만 | 3 | 11,107 / 1,005 | 40,082ms |
| interpreted+072해석비용 | 6 | 11,686 / 6,359 | 217,401ms |

plain은v42입력12,730→10,321(-18.9%),해석포함은074입력14,190→11,107(-21.7%).
토큰감소가의미개선을보증하지않는다. 신규전체wall80,232ms/load7,498ms,usage누락0.
역사SHA/시점/cache와coldload가달라정밀paired성능개선으로해석하지않는다.
시작GPU0MiB43°C,중간6383MiB63%63°C,종료6385MiB0%58°C(snapshot).
모델동시1,실행중편집/pytest0. 직접57tests/Ruff/mypy PASS; 전체pytest미실행.

**다음선택:** 입력사본삭제·자연어덧붙이기는후순위로돌린다. 한응답에서여러Resource의
판정이서로영향받는지확인하기위해, 전체catalog/원문은유지하면서한Resource의
membership+details를FIRST하나로판정하는작은개발진단을검토한다. 기존전체membership→
selecteddetails(v43),catalog축소family와는구분한다. 긍정/부정·기존DraftUPDATE반례를
포함하고미시험Resource를NOT_REQUIRED로채우지않는다. 호출증가를숨기지않는다.

Product source/활성Prompt/State/Graph0, Provider/Approval/WRITE0. Source-only점수로
RU→ToolRoute/업무성공을승계하지않는다. Canonical92신규실행0, Production유지.

## 원근거

- plan `evaluation/results/075-source-user-input-plan/preregistered-plan.json`, object hash
  `e2ecbf7ed782af8d4904aae004bd10b355c57384affc7ee519318b553f288e83`.
- raw `evaluation/results/075-source-user-input-t1/raw.json`, bytes hash
  `18fd562e76e106221da090376a802cdd798b0ebc2fc0cc24ae42d0056eb016d0`.
- Source admission/arm별비용은동폴더source-admission.json. rawCaseID중복은plan순서와
  exactpayload/hash로결속하며CaseID만으로합치지않는다.상세원문은로컬ignore영역보존.
- Dataset/Fixture/modeldigest는074와동일이며plan에fullhash결속.
