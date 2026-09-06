import { afterEach, expect, test, vi } from "vitest";
import { modifyAction } from "../../../../src/features/approval/api/action_commands";

afterEach(() => vi.restoreAllMocks());

test("Natural language is sent untouched to the existing versioned modification endpoint", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ applied: true }), { status: 200, headers: { "content-type": "application/json" } }));
  const request = "예정일을 9월 8일로 바꾸고 메모는 빼줘";
  await modifyAction({ action_id: "action", command_id: "modify", expected_version: 3, modification_request: request });
  expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/actions/action/modify");
  expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({ api_contract_version: "1", command_id: "modify", expected_version: 3, arguments_patch: {}, modification_request: request });
});

test("Direct editing preserves explicit removal and leaves unmentioned fields absent", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ applied: true }), { status: 200, headers: { "content-type": "application/json" } }));
  await modifyAction({ action_id: "action", command_id: "modify", expected_version: 3, arguments_patch: { notes: "", due: null } });
  expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({ api_contract_version: "1", command_id: "modify", expected_version: 3, arguments_patch: { notes: "", due: null } });
});
