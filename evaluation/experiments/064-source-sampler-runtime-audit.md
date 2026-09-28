# 064 — Source sampler runtime 감사

## 범위와 결론

2026-09-28에 기존 코드·raw·로컬 Ollama 로그와 공식 버전 고정 소스를 읽었다. 최종 검토 시각은 21:12 KST이고 문서 작성 시 HEAD는 `661b2503702fa88efdbb86562ae70924d1f7ce4e`다. 새 모델 호출·pytest·업무 Provider 호출·제품/Prompt 변경은 0이다.

현재 Ollama 0.34.0 / qwen3.5:9b의 **presence penalty 1.5가 실제 sampler에 전달·적용되는 경로**는 확인했다. Source의 temperature 0.05는 이를 끄지 않는다. 하지만 이것이 Source 누락/과잉 선택의 원인이라는 증거는 아직 없다. 다음 비교 계획은 [v42 기준](064-source-presence-v42-criteria.md)이며 이 감사 자체는 후보 성능 실험이 아니다.

## 기존 비교와 제품 wire

- 현재 `src/`, `scripts/`, `tests/`, `evaluation/experiments/`, 남아 있는 ignored results와 `git log --all -S presence_penalty -- src scripts evaluation`에서 **Source presence penalty만 통제한 비교를 찾지 못했다**. 초기 실험의 모든 raw가 남아 있지는 않아 과거 전체에서 한 번도 실행하지 않았다고 단정하지 않는다.
- v31은 prohibition owner의 model-default temperature 대 explicit 0 비교다. presence penalty는 양 arm 모두 미전송/model default였다. 이후 sparse/Goal-input 실험도 presence 단독 비교가 아니다.
- `adapters/llm/ollama/transport.py::invoke_structured`는 `num_ctx=16384`와 지정된 temperature/seed만 options에 넣는다. `structured_inference_router.py::_runtime_policy_for_prompt`는 Source temperature를 0.05로 결속한다. presence/frequency/repeat penalty override는 없다.
- v41 실제 FIRST 5개의 options는 `num_ctx=16384, temperature=0.05, seed=20260923`, `think=false`다. `/api/show`의 모델 defaults는 presence penalty 1.5, temperature 1, top_k 20, top_p 0.95다. wire의 temperature만 모델 default를 대체한다.
- 모델 digest: `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`. show parameters hash: `c7f3a462076d3f09e9378c7a143c5a83f7a7b9807e838014ee34a71f29e1c254`.

## 실제 소비 경로 — 공식 소스와 관측

현재 `/api/version`은 0.34.0이며 실행 backend는 `llama-server`다. 과거 Go runner가 옵션을 무시했다는 [Ollama #14493](https://github.com/ollama/ollama/issues/14493)을 현재 버전의 동작으로 승계하지 않는다.

1. Ollama v0.34.0은 GGML 모델을 upstream llama-server subprocess로 실행한다. [llm/server.go 106–109](https://github.com/ollama/ollama/blob/v0.34.0/llm/server.go#L106). 연결된 llama.cpp 버전은 [LLAMA_CPP_VERSION](https://github.com/ollama/ollama/blob/v0.34.0/LLAMA_CPP_VERSION)의 `b10760`이다.
2. 모델 defaults → model options → request options 순으로 병합한다. 따라서 request의 명시적 0도 default와 구별된다. [server/routes.go 137–152](https://github.com/ollama/ollama/blob/v0.34.0/server/routes.go#L137).
3. llama-server 요청 struct에는 penalty 필드가 있으며, Completion이 `req.Options.PresencePenalty` 등을 전달한다. [llm/llama_server.go 1396 이후](https://github.com/ollama/ollama/blob/v0.34.0/llm/llama_server.go#L1396), [1563 이후](https://github.com/ollama/ollama/blob/v0.34.0/llm/llama_server.go#L1563). JSON schema/grammar 전달은 별도다.
4. b10760 sampler는 최근 token 출현을 세고 해당 후보 logit에서 presence penalty를 뺀다. [src/llama-sampler.cpp 2919 이후](https://github.com/ggml-org/llama.cpp/blob/b10760/src/llama-sampler.cpp#L2919), [2976](https://github.com/ggml-org/llama.cpp/blob/b10760/src/llama-sampler.cpp#L2976). [common/sampling.cpp 380 이후](https://github.com/ggml-org/llama.cpp/blob/b10760/common/sampling.cpp#L380)에서 penalty sampler를 구성한다.

로컬 `server.log`의 비민감 관측: 시작 line 5는 2026-09-28 13:32:22 KST / version 0.34.0이다. v41 실행 구간의 lines 38419/38456/38500/38546/38595는 sampler chain에 `penalties`가 있음을 보이며, lines 38421/38458/38502/38548/38597는 `repeat_last_n=64, repeat_penalty=1, frequency_penalty=0, presence_penalty=1.5`를 기록한다. 각 다음 parameter 줄은 temperature 0.05 / top_k 20 / top_p 0.95다. 20:57:20–20:57:57의 직렬 generate 5회와 대응한다.

이 로그의 2026-09-28 약 21:06 KST read-shared snapshot은 3,714,585 bytes, SHA256 `205623daae49832377af5609b06175ac66c72537edef8610a339ebcdc7d52e55`다. 로그는 계속 append될 수 있다. 개인 경로·요청 원문·전체 로그는 이 문서에 포함하지 않는다.

## 재사용 baseline의 역사적 runtime 결속 한계

원 baseline 5개는 다음 실제 FIRST다. 017/049는 Work-span 후보 upstream을 거친 frozen Source 입력이며 Product 전체 baseline으로 이름을 바꾸지 않는다. v42에서 각 arm이 **동일 frozen Source 입력**을 사용하는 것과 upstream 실행 SHA가 같은 것은 다르다.

| Core | 원 raw 계열 / arm | 실행 HEAD | input/output tokens | raw latency ms | 상관 로그 종료 KST / lines |
| --- | --- | --- | --- | --- | --- |
| 005 | work-span-codec-v35-connected-t1 / production | 3142c5c3 | 4076 / 171 | 8273 | 18:51:37 / 33699–33729 |
| 009 | connected-core8-t1 / production | c8708b1d | 3854 / 162 | 7896 | 18:04:26 / 27541–27571 |
| 017 | work-span-codec-v35-connected-t1 / work-span-codec-v35 | 3142c5c3 | 4150 / 278 | 11994 | 18:53:03 / 34495–34527 |
| 049 | work-span-codec-v35-connected-t1 / work-span-codec-v35 | 3142c5c3 | 4504 / 345 | 14468 | 18:54:05 / 34931–34964 |
| 059 | connected-core8-continuation-t1 / production | 1e66bc3a | 3858 / 163 | 7964 | 18:21:34 / 31748–31778 |

각 원 경로는 `evaluation/results/064-<계열>/CASE-CORE-<번호>/<arm>/calls.json`이며 선택 call index는 3이다. 모든 위 로그 구간은 penalty 1.5 / temperature 0.05 / top_k 20 / top_p 0.95다. input/output token 쌍이 원 raw와 일치하고 HTTP duration은 raw latency보다 약 11–17 ms 길며 결과 파일 수정 시각 전이다. 같은 로그 시작의 0.34.0 서버와 **높은 상관 일치**를 보인다. 같은 token 수의 후속 재실행 로그도 있으므로 token 수 하나만으로 매칭하지 않았다.

다만 원 3개 plan에는 Ollama version/backend build/show parameters가 없고, calls에는 호출별 wall timestamp·server task ID가 없다. wire hash와 로그 task ID의 직접 결속도 없다. fixture reference time이 들어간 `run_budget.started_at_ms`나 파일 mtime을 호출 시각으로 취급하지 않는다. 따라서 역사적 consumer 동일성을 완전하게 검증한 fresh paired 실험이라고 주장할 수 없다.

원 plan 파일 SHA256:

- v35: `4163a93be350fc02b38b5505a1a938dd79fd8d6a3e9488e9b13d716424518ff4`
- Core8: `be5416a01d18e4ac8bf03e374e565e12669d35dfb0b440c80c7d3a834e1f4d02`
- continuation: `29b131bc6cdd7da9c018dfa8e17ac705d3cf0ebd31d72065b0ee7411eff2de10`

기존 5개 재사용은 위 한계를 가진 bounded 탐색 비교로 가능하지만, v42는 실행 전에 **현행 default arm 5 + penalty 0 arm 5의 fresh matched 비교**로 결정했다. 역사적 consumer와 현재 consumer의 미결속을 제거하고 동일 frozen input/runtime에서 penalty만 비교하기 위해서다. 원 5개는 역사 참고로 유지하며 신규 arm의 점수로 승계하지 않는다. 이 감사는 새 호출을 수행하지 않는다.

## 가설, 반례, 다음 판단

Source exact-set schema는 후보마다 반복 key/enum/Work ID와 required-information 목록을 출력한다. penalty는 최근 token의 확률에 영향을 줄 수 있으므로 이전 Prompt 축소와 다른 runtime 축을 조사할 근거가 있다. 그러나 grammar가 강제하는 key와 선택 가능한 의미 token의 영향은 같다고 단정할 수 없다. token별 logit 관측도 없다.

중요한 반례는 v41이다. penalty 1.5 아래서도 5/5가 10개 후보 행과 반복 key를 포함해 schema를 통과했다. 009는 REQUIRED 4개 행을 반복해 생성했고, 다른 Case도 NOT_REQUIRED를 반복했다. 따라서 “반복 출력이 불가능하다”, “penalty가 모든 Source 누락을 만들었다”는 설명은 틀리다. 005의 selected 범위 변화, 017의 필요한 Task 누락, 049의 Mail/Task 누락, 059의 새 Draft와 기존 Source 혼동은 여전히 의미 오류이며 penalty 원인으로 확정하지 않는다.

v41 raw SHA256: `91772da9aea4514cc12e4c6bb0195389e4ab414a9252549871feb8b3f0b042b7`. 축소 Prompt 후보는 다음 penalty 비교의 Prompt baseline으로 사용하지 않는다. 원 Product Prompt/input/schema/options를 유지하고 penalty만 바꾸며, FIRST 구조·의미·usage를 따로 기록한다. 한 번 개선되어도 반복 안정성이나 RU 이후 업무 성공을 증명하지 않는다. 미개선이면 penalty 수치를 연속 탐색하지 않는다.

최종 상태: **runtime 소비 확인 / Source 의미 실패의 원인 미확정 / 새 비교 미실행**. 이 감사의 변경은 본 문서 1개이며 commit/push는 부모 작업에서 처리한다.
