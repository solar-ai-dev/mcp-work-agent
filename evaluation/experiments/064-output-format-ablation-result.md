# 064 v36 — Output constrained decoding의 의미/형식 분리 진단

실행 SHA `9813416e4624abf190dd3e5c15d891470c5342bb`. 사전 기준은
`064-output-format-ablation-criteria.md`, Core005/017/049 × 두 arm 각 1회, 실제 6calls다.
Prompt/input/schema/options는 동일하고 후보에서 top-level `format` 하나만 제거했다.
원 v35 payload를 Product assembler/transport로 재구성한 wire hash가 모두 일치했다.

모델은 `qwen3.5:9b`, digest
`6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`.
Output 실제 temperature0, seed20260923, ctx16384, thinkfalse, timeout180초.
Dataset/fixture와 Case reference time은 frozen plan에 결속했고 변경하지 않았다.

## 실제 결과

| Case | schema_constrained | format_omitted | 최초 차이 |
|---|---|---|---|
| 005 | 구조 VALID, 의미 FAIL: 조회에 TASK UPDATE + GMAIL SEND를 추가 | strict INVALID_JSON. 단일 JSON 코드펜스 내부는 빈 Output으로 올바름 | 동일 입력의 decoding 제약 변경 후 불필요 WRITE가 사라졌으나 반환 wrapper가 계약 위반 |
| 017 | 구조/Output owner 의미 PASS: Draft CREATE | strict INVALID_JSON. 펜스 내부는 같은 Draft CREATE/Work binding | 의미 회귀는 보이지 않지만 구조적으로 소비 불가 |
| 049 | 구조/Output owner 의미 PASS: Task/Event/Draft CREATE | strict INVALID_JSON. 펜스 내부는 같은 세 CREATE/Work binding | 의미 회귀는 보이지 않지만 구조적으로 소비 불가 |

사전 strict 판정은 **3/3 → 0/3**, 구조와 의미를 합친 owner gate는
**2 PASS / 0 PARTIAL / 1 FAIL → 0 PASS / 0 PARTIAL / 3 FAIL**이다.
별도 내용 검수는 **2/3 → 3/3**이나, 이를 Product 통과로 승격하지 않는다.
원 raw의 INVALID_JSON/UNREVIEWED와 실패를 그대로 보존했다. 후속 검수는 코드펜스 안
객체의 의미를 사람이 관측한 것이지 파서를 변경하거나 raw를 재채점해 통과시킨 것이 아니다.

두 arm의 입력 hash가 같고 candidate wire는 format 삭제 외 동일하다. constrained의
세 응답은 원 v35 Output FIRST와도 byte-identical이다. 이번 005에서는 grammar 영향이
관측됐지만, 모든 요청/owner에서의 원인이나 장기 안정성을 확정하지 않는다.

이 schema는 수신자·시간·Source·작성 내용을 표현하지 않는다. 017의 과잉 Source와
049의 upstream 시간 역할 오류는 그대로 미해결이며 이번 Output 오답으로 재귀속하지 않는다.
1 Work → 3 Output을 허용하고 Work 개수나 분해 모양을 Gold로 강제하지 않았다.

## 비용·안전·자원

| 실제 측정 | schema_constrained | format_omitted |
|---|---:|---:|
| HTTP model calls | 3 | 3 |
| input / output tokens | 8,848 / 151 | 8,848 / 208 |
| reported latency 합계 | 14,898ms | 8,685ms |
| wall latency 합계 | 14,952ms | 8,780ms |
| usage 누락 / repair / retry | 0 / 0 / 0 | 0 / 0 / 0 |

첫 constrained 호출에는 cold load 영향이 있으므로 합계로 성능 개선을 주장하지 않는다.
입력 token 수는 pair별 정확히 같았다. 모델은 1개씩 순차 실행했고 다른 pytest/mypy를
겹치지 않았다. 시작 RAM 여유20.2GB/GPU유휴44°C, 종료 관측 VRAM6385MiB/57°C다.
Graph/upstream 재실행 0, 외부 업무 Provider READ/WRITE/SEND 0. 예외·timeout 0.

## 판단과 다음 선택

**format 생략의 Product 채택은 하지 않는다.** parser의 JSON 문법 경계에서 세 건이 모두
실패했다. 기존 Product parser/repair는 json.loads 기반이며 코드펜스를 자동 허용하지 않는다.
현재 올바른 내용이 repair 후에도 보존된다는 근거도 없다.

다음 최소 비교는 [공식 Ollama API](https://docs.ollama.com/api/generate)의 `format:"json"`이다. JSON 문법만 제약하고 기존 본문
schema/Prompt와 사후 schema·owner validator는 유지한다. 005를 위한 의미 규칙이나
문자열 예외를 추가하지 않는다. 동일 constrained baseline을 또 실행할 이유가 없어 이 raw를
재사용하고, 새 JSON-mode 세 입력을 각 1회만 사전 고정한다. 기존6회와 신규3회의 분모를
섞거나 이전 실패를 대체하지 않는다. 다음 비교는 별도 사전 기준·SHA·plan으로 기록한다.

## 원 근거

- `evaluation/results/064-output-format-v36-t1/raw.json`
  SHA256 `c1f7c6e54c035dbb5baf556f310301599a78f93f5d756b8e320835cd8f646ef3`.
- `evaluation/results/064-output-format-v36-t1-plan/preregistered-plan.json`
  파일 SHA256 `ec302deb0e21a3198d1b7d6905f00ea7648daa5177fe67765b275bf4234f92d4`;
  plan object hash `f7ff237f7e1dbb34a8ef84ff04c7dfff00503d990754ae5bafd7b2b7201e9695`.
- 상세 raw는 로컬 ignore 정책을 유지하고 이 검증 요약과 실행기는 원격에 보존한다.
