import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { useTasks } from "../../../src/features/resource_browser/tasks_controller";
import * as resourceApi from "../../../src/features/resource_browser/api/list_resources";
import type { ResourceListResponse } from "../../../src/api/contract";

afterEach(() => vi.restoreAllMocks());

function page(id: string, completed = false): ResourceListResponse {
  return { schema_version: 1, next_page_token: null, total_count: 1, projection_version: "1", items: [{ schema_version: 1, selection_handle: id, resource_id: id, parent_id: id, source: "tasks", resource_type: "task", title: id, link_url: null, version: "1", related_resource_ids: [], metadata: { task_status: completed ? "completed" : "incomplete", scheduled_date: "2026-09-10" } }] };
}

test("Account scope invalidates pending preload and completed responses", async () => {
  let oldPreload!: (value: ResourceListResponse) => void;
  let oldCompleted!: (value: ResourceListResponse) => void;
  vi.spyOn(resourceApi, "listResources")
    .mockImplementationOnce(() => new Promise((resolve) => { oldPreload = resolve; }))
    .mockImplementationOnce(() => new Promise((resolve) => { oldCompleted = resolve; }))
    .mockImplementation(async (request) => page("new-account", request.source === "tasks" && request.statusScope === "completed"));
  const { result, rerender } = renderHook(({ accountId }) => useTasks({ accountId, parentId: null, active: true, filter: "" }), { initialProps: { accountId: "old" } });
  act(() => { void result.current.preload(); void result.current.loadCompleted(); });
  rerender({ accountId: "new" });
  await act(async () => { await result.current.preload(); await result.current.loadCompleted(); });
  await act(async () => { oldPreload(page("old-account")); oldCompleted(page("old-account", true)); });
  expect(result.current.count).toEqual({ value: 1, exact: true });
  expect(result.current.completed.items.map((item) => item.resource_id)).toEqual(["new-account"]);
  await act(async () => result.current.loadPage(0));
  expect(result.current.items.map((item) => item.resource_id)).toEqual(["new-account"]);
});

test("Changing Task List clears completed data and ignores an obsolete incomplete response", async () => {
  let oldPage!: (value: ResourceListResponse) => void;
  const browse = vi.spyOn(resourceApi, "listResources")
    .mockImplementationOnce(() => new Promise((resolve) => { oldPage = resolve; }))
    .mockImplementation(async (request) => page(request.source === "tasks" ? request.taskListId ?? "default" : "unexpected"));
  const { result, rerender } = renderHook(({ parentId }) => useTasks({ accountId: "account", parentId, active: true, filter: "" }), { initialProps: { parentId: "old-list" } });
  act(() => { void result.current.loadPage(0); });
  rerender({ parentId: "new-list" });
  await act(async () => result.current.loadPage(0));
  await act(async () => oldPage(page("old-list")));
  await waitFor(() => expect(result.current.items.map((item) => item.resource_id)).toEqual(["new-list"]));
  expect(result.current.completed.initialized).toBe(false);
  expect(browse).toHaveBeenLastCalledWith(expect.objectContaining({ taskListId: "new-list" }));
});
