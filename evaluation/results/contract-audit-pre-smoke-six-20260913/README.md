# Contract Audit PRE Production Smoke — 2026-09-13

| Case | Contract | Business | Wait/Resume | Terminal | First failure | LLM | READ | WRITE | SEND | Run | Trace |
|---|---|---|---|---|---|---:|---:|---:|---:|---|---|
| 대상 없는 일정 | FAIL | FAIL | confirmation/resume | BLOCKED | Request Understanding resume budget | 14 | 0 | 0 | 0 | `180e8b44-9497-4170-aea5-4ebdd4d278ad` | [initial](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a09736-1ed6-7ad3-8d55-1dae6a612521/run/01a09736-1ed6-7ad3-8d55-1dae6a612521) · [resume](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a09737-7d89-7e83-b22f-7eb08ff39479/run/01a09737-7d89-7e83-b22f-7eb08ff39479) |
| Selected Event | FAIL | FAIL | none | BLOCKED | `identify_output_responsibilities` | 8 | 0 | 0 | 0 | `b8dc45fd-d746-4846-93a5-c40d43bf288e` | [trace](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a09739-398d-7db2-b045-9ea30a4c1443/run/01a09739-398d-7db2-b045-9ea30a4c1443) |
| Atlas Draft | FAIL | FAIL | none | BLOCKED | `identify_goal` output schema | 2 | 0 | 0 | 0 | `7118fe0b-d0ea-4948-b10b-76146c74ea6c` | [trace](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a0973e-65a6-70f1-b406-b1db2f36df55/run/01a0973e-65a6-70f1-b406-b1db2f36df55) |
| Juniper 전체 제목 | FAIL | FAIL | none | COMPLETED | `identify_goal` coverage 의미 유실 | 14 | 13 | 0 | 0 | `26b0eb24-37fe-4074-a49e-8be3b6f15e04` | [trace](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a0973a-6354-7683-aca2-2cb2eb2a1ee3/run/01a0973a-6354-7683-aca2-2cb2eb2a1ee3) |
| Atlas q19 | PASS | PASS | none | COMPLETED | 최종 도달 | 14 | 13 | 0 | 0 | `e9cfabd1-9c3a-4be9-8d88-7e2045ebc7e4` | [trace](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a0973c-86d2-7792-b9bc-5cf92f7e862e/run/01a0973c-86d2-7792-b9bc-5cf92f7e862e) |
| Quartz Draft | FAIL | FAIL | approval 미도달 | RECOVERY_REQUIRED | `compose_arguments_per_output_route` | 12 | 1 | 0 | 0 | `93146f90-4f45-42ad-95ef-c5752df9028c` | [trace](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a0973f-9841-7431-a814-e2243dfa5542/run/01a0973f-9841-7431-a814-e2243dfa5542) |

## 집계

- Product SHA: `fed967d280533b25b2c752beb95795188f24efa0`
- Business PASS: 1/6
- Contract PASS: 1/6
- LangSmith execution trace: 6/6
- LLM calls: 64
- Connector READ: 27
- Provider WRITE: 0
- Provider SEND: 0
- 공식 initial Domain Run: 6
- rerun-to-pass: 0
- Batch 중 제품·Prompt·Schema·fixture·모델 변경: 0

상세 판정과 안전한 typed projection은 `summary.json`, `case-*.json`, `traces/index.json`에 기록했다. Raw Prompt/completion, Provider payload, credential, Resource identity는 포함하지 않았다.
