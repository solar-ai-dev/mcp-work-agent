import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { presentResource, ResourceSidebar } from "../../../src/features/resource_browser/resource_sidebar";
import * as resourceApi from "../../../src/features/resource_browser/api/list_resources";
import type { ResourceItem, ResourceListResponse } from "../../../src/api/contract";

afterEach(() => vi.restoreAllMocks());

const emptyPage: ResourceListResponse = { schema_version: 1, items: [], next_page_token: null, total_count: 0, projection_version: "1" };

function taskItem(id: string, list: string, status = "incomplete"): ResourceItem {
  return { schema_version: 1, selection_handle: `${list}:${id}`, source: "tasks", resource_type: "task", resource_id: id, parent_id: list, title: id, link_url: null, version: "1", related_resource_ids: [list], metadata: { scheduled_date: "2026-09-10", task_status: status } };
}

function mockBrowse() {
  vi.spyOn(resourceApi, "getResourceCount").mockResolvedValue({ schema_version: 1, source: "gmail", exact_count: 0, as_of_ms: 1 });
  return vi.spyOn(resourceApi, "listResources").mockImplementation(async (request) => {
    if (request.source !== "tasks") return emptyPage;
    const list = request.taskListId ?? "first";
    return { ...emptyPage, items: [taskItem(request.statusScope === "completed" ? `完了-${list}` : `future-${list}`, list, request.statusScope ?? "incomplete")] };
  });
}

test("Task List selection discovers another page and shows future tasks without changing defaults", async () => {
  const browse = mockBrowse();
  const lists = vi.spyOn(resourceApi, "listTaskLists").mockImplementation(async (token) => ({ schema_version: 1, items: [{ schema_version: 1, tasklist_id: token ? "validation" : "first", title: token ? "GWA E2E Validation" : "My Tasks" }], next_page_token: token ? null : "opaque-next" }));
  render(<ResourceSidebar scopeKey="session" accountId="account" connected timezone="Asia/Seoul" onProjectionChange={vi.fn()} />);
  fireEvent.click(screen.getByRole("tab", { name: /태스크/ }));
  fireEvent.click(await screen.findByRole("button", { name: "목록 더 불러오기" }));
  await screen.findByRole("option", { name: "GWA E2E Validation" });
  fireEvent.change(screen.getByLabelText("조회할 태스크 목록"), { target: { value: "validation" } });
  await screen.findByText("future-validation");
  expect(screen.getByText("9월 10일 (목)")).toBeInTheDocument();
  expect(screen.queryByText("future-first")).not.toBeInTheDocument();
  expect(lists).toHaveBeenCalledWith("opaque-next");
  expect(browse).toHaveBeenCalledWith(expect.objectContaining({ source: "tasks", taskListId: "validation", pageSize: 100 }));
  fireEvent.click(screen.getByRole("button", { name: "태스크 정렬 메뉴" }));
  fireEvent.click(screen.getByRole("menuitemradio", { name: "날짜순" }));
  await screen.findByText("future-validation");
  fireEvent.click(screen.getByRole("button", { name: "태스크 정렬 메뉴" }));
  fireEvent.click(screen.getByRole("menuitemradio", { name: "기본 순서" }));
  await screen.findByText("future-validation");
  expect(screen.getByRole("tab", { name: /태스크/ })).toHaveTextContent("1");
  fireEvent.click(screen.getByRole("button", { name: /완료됨/ }));
  await screen.findByText(/完了-validation/);
  expect(screen.queryByText(/完了-first/)).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("조회할 태스크 목록"), { target: { value: "" } });
  await screen.findByText("future-first");
});

test("Task List discovery failure is not an empty list and refresh can recover", async () => {
  mockBrowse();
  vi.spyOn(resourceApi, "listTaskLists").mockRejectedValueOnce(new Error("denied")).mockResolvedValue({ schema_version: 1, items: [], next_page_token: null });
  render(<ResourceSidebar scopeKey="session" accountId="account" connected timezone="Asia/Seoul" onProjectionChange={vi.fn()} />);
  fireEvent.click(screen.getByRole("tab", { name: /태스크/ }));
  expect(await screen.findByRole("alert")).toHaveTextContent("태스크 목록을 불러오지 못했습니다");
  expect(screen.queryByText("사용 가능한 태스크 목록이 없습니다.")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "태스크 목록 새로고침" }));
  await screen.findByText("사용 가능한 태스크 목록이 없습니다.");
});

test("Account change discards stale Task List discovery and selected container", async () => {
  mockBrowse();
  let resolveOld!: (value: Awaited<ReturnType<typeof resourceApi.listTaskLists>>) => void;
  vi.spyOn(resourceApi, "listTaskLists").mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; })).mockResolvedValue({ schema_version: 1, items: [{ schema_version: 1, tasklist_id: "new-list", title: "New account list" }], next_page_token: null });
  const onProjectionChange = vi.fn();
  const { rerender } = render(<ResourceSidebar scopeKey="session" accountId="old" connected timezone="Asia/Seoul" onProjectionChange={onProjectionChange} />);
  fireEvent.click(screen.getByRole("tab", { name: /태스크/ }));
  await waitFor(() => expect(resolveOld).toBeDefined());
  rerender(<ResourceSidebar scopeKey="session" accountId="new" connected timezone="Asia/Seoul" onProjectionChange={onProjectionChange} />);
  await screen.findByRole("option", { name: "New account list" });
  await act(async () => resolveOld({ schema_version: 1, items: [{ schema_version: 1, tasklist_id: "old-list", title: "Old account list" }], next_page_token: null }));
  expect(screen.queryByRole("option", { name: "Old account list" })).not.toBeInTheDocument();
  expect(screen.getByLabelText("조회할 태스크 목록")).toHaveValue("");
});

test("resource sidebar presents exact server-projected provider titles", () => {
  expect(presentResource({ schema_version: 1, selection_handle: "a", source: "tasks", resource_type: "task", resource_id: "a", title: "GWA-DEADLINE-ONLY-TEST", link_url: null, version: "1", related_resource_ids: [], metadata: {} }).title).toBe("GWA-DEADLINE-ONLY-TEST");
  expect(presentResource({ schema_version: 1, selection_handle: "b", source: "gmail", resource_type: "gmail_thread", resource_id: "b", title: "예산 검토 요청", subject: "예산 검토 요청", link_url: null, version: "1", related_resource_ids: [], metadata: {} }).title).toBe("예산 검토 요청");
});
