import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
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

function sidebarProps(overrides: Partial<ComponentProps<typeof ResourceSidebar>> = {}): ComponentProps<typeof ResourceSidebar> {
  return {
    scopeKey: "session",
    googleAccountId: "google-account",
    githubAccountId: null,
    googleConnected: true,
    githubConnected: false,
    githubRepositories: [],
    timezone: "Asia/Seoul",
    onProjectionChange: vi.fn(),
    ...overrides,
  };
}

test("Task List selection discovers another page and shows future tasks without changing defaults", async () => {
  const browse = mockBrowse();
  const lists = vi.spyOn(resourceApi, "listTaskLists").mockImplementation(async (token) => ({ schema_version: 1, items: [{ schema_version: 1, tasklist_id: token ? "validation" : "first", title: token ? "GWA E2E Validation" : "My Tasks" }], next_page_token: token ? null : "opaque-next" }));
  render(<ResourceSidebar {...sidebarProps()} />);
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
  render(<ResourceSidebar {...sidebarProps()} />);
  fireEvent.click(screen.getByRole("tab", { name: /태스크/ }));
  expect(await screen.findByRole("alert")).toHaveTextContent("태스크 목록을 불러오지 못했습니다");
  expect(screen.queryByText("사용 가능한 태스크 목록이 없습니다.")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "태스크 목록 새로고침" }));
  await screen.findByText("사용 가능한 태스크 목록이 없습니다.");
});

test("Task refresh replaces a selected resource handle without duplicating its identity", async () => {
  let currentHandle = "stale-handle";
  vi.spyOn(resourceApi, "getResourceCount").mockResolvedValue({ schema_version: 1, source: "gmail", exact_count: 0, as_of_ms: 1 });
  vi.spyOn(resourceApi, "listTaskLists").mockResolvedValue({ schema_version: 1, items: [], next_page_token: null });
  vi.spyOn(resourceApi, "listResources").mockImplementation(async (request) => request.source === "tasks" && request.statusScope !== "completed"
    ? { ...emptyPage, total_count: 1, items: [{ ...taskItem("task-1", "list-1"), selection_handle: currentHandle }] }
    : emptyPage);
  const onProjectionChange = vi.fn();
  render(<ResourceSidebar {...sidebarProps({ onProjectionChange })} />);
  fireEvent.click(screen.getByRole("tab", { name: /태스크/ }));
  const selection = await screen.findByRole("checkbox", { name: "task-1 선택" });
  fireEvent.click(selection);
  await waitFor(() => expect(onProjectionChange).toHaveBeenLastCalledWith(expect.objectContaining({
    selectedContext: expect.objectContaining({ selectionHandles: ["stale-handle"] }),
  })));

  currentHandle = "current-handle";
  fireEvent.click(screen.getByRole("button", { name: "현재 목록 새로고침" }));

  await waitFor(() => expect(onProjectionChange).toHaveBeenLastCalledWith(expect.objectContaining({
    selectedContext: expect.objectContaining({
      resourceIds: ["task-1"],
      selectionHandles: ["current-handle"],
    }),
  })));
});

test("Account change discards stale Task List discovery and selected container", async () => {
  mockBrowse();
  let resolveOld!: (value: Awaited<ReturnType<typeof resourceApi.listTaskLists>>) => void;
  vi.spyOn(resourceApi, "listTaskLists").mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; })).mockResolvedValue({ schema_version: 1, items: [{ schema_version: 1, tasklist_id: "new-list", title: "New account list" }], next_page_token: null });
  const onProjectionChange = vi.fn();
  const { rerender } = render(<ResourceSidebar {...sidebarProps({ googleAccountId: "old", onProjectionChange })} />);
  fireEvent.click(screen.getByRole("tab", { name: /태스크/ }));
  await waitFor(() => expect(resolveOld).toBeDefined());
  rerender(<ResourceSidebar {...sidebarProps({ googleAccountId: "new", onProjectionChange })} />);
  await screen.findByRole("option", { name: "New account list" });
  await act(async () => resolveOld({ schema_version: 1, items: [{ schema_version: 1, tasklist_id: "old-list", title: "Old account list" }], next_page_token: null }));
  expect(screen.queryByRole("option", { name: "Old account list" })).not.toBeInTheDocument();
  expect(screen.getByLabelText("조회할 태스크 목록")).toHaveValue("");
});

test("resource sidebar presents exact server-projected provider titles", () => {
  expect(presentResource({ schema_version: 1, selection_handle: "a", source: "tasks", resource_type: "task", resource_id: "a", title: "GWA-DEADLINE-ONLY-TEST", link_url: null, version: "1", related_resource_ids: [], metadata: {} }).title).toBe("GWA-DEADLINE-ONLY-TEST");
  expect(presentResource({ schema_version: 1, selection_handle: "b", source: "gmail", resource_type: "gmail_thread", resource_id: "b", title: "예산 검토 요청", subject: "예산 검토 요청", link_url: null, version: "1", related_resource_ids: [], metadata: {} }).title).toBe("예산 검토 요청");
});

test.each([
  ["Google만 연결", true, false, ["메일", "캘린더", "태스크"], ["GitHub Issues"]],
  ["GitHub만 연결", false, true, ["GitHub Issues"], ["메일", "캘린더", "태스크"]],
  ["모두 연결", true, true, ["메일", "캘린더", "태스크", "GitHub Issues"], []],
  ["모두 미연결", false, false, [], ["메일", "캘린더", "태스크", "GitHub Issues"]],
])("%s이면 연결된 Connector의 Resource 탭만 표시한다", (_label, googleConnected, githubConnected, visible, hidden) => {
  mockBrowse();
  vi.spyOn(resourceApi, "listTaskLists").mockResolvedValue({ schema_version: 1, items: [], next_page_token: null });
  render(<ResourceSidebar {...sidebarProps({
    googleAccountId: googleConnected ? "google-account" : null,
    githubAccountId: githubConnected ? "github-account" : null,
    googleConnected,
    githubConnected,
    githubRepositories: githubConnected ? ["solar-ai-dev/google-work-agent"] : [],
  })} />);
  for (const name of visible) expect(screen.getByRole("tab", { name: new RegExp(name) })).toBeInTheDocument();
  for (const name of hidden) expect(screen.queryByRole("tab", { name: new RegExp(name) })).not.toBeInTheDocument();
  if (!googleConnected && !githubConnected) {
    expect(screen.getByText("연결된 Connector의 자료가 여기에 표시됩니다.")).toBeInTheDocument();
  }
});

test("네 Resource 사이 전환 시 이전 상세를 제거하고 GitHub Issue를 탐색한다", async () => {
  const issue: ResourceItem = {
    schema_version: 1,
    selection_handle: "github-selection",
    source: "github",
    resource_type: "github_issue",
    resource_id: "solar-ai-dev/google-work-agent#181",
    parent_id: "solar-ai-dev/google-work-agent",
    title: "Runtime closure",
    subtitle: "#181",
    link_url: "https://github.com/solar-ai-dev/google-work-agent/issues/181",
    version: "1",
    related_resource_ids: ["solar-ai-dev/google-work-agent"],
    metadata: { repository: "solar-ai-dev/google-work-agent", issue_number: 181, description: "Sidebar", issue_state: "OPEN", labels: [], assignees: [] },
  };
  mockBrowse().mockImplementation(async (request) => request.source === "github" ? { ...emptyPage, items: [issue], total_count: 1 } : emptyPage);
  vi.spyOn(resourceApi, "listTaskLists").mockResolvedValue({ schema_version: 1, items: [], next_page_token: null });
  const onProjectionChange = vi.fn();
  const { rerender } = render(<ResourceSidebar {...sidebarProps({ githubAccountId: "github-account", githubConnected: true, githubRepositories: ["solar-ai-dev/google-work-agent"], onProjectionChange })} />);

  for (const name of ["캘린더", "태스크", "GitHub Issues", "메일"]) {
    fireEvent.click(screen.getByRole("tab", { name: new RegExp(name) }));
    expect(screen.getByRole("tab", { name: new RegExp(name) })).toHaveAttribute("aria-selected", "true");
  }
  fireEvent.click(screen.getByRole("tab", { name: /GitHub Issues/ }));
  expect(await screen.findByText("Runtime closure")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox", { name: "Runtime closure 선택" }));
  fireEvent.click(screen.getByRole("button", { name: /Runtime closure/ }));
  expect(screen.getByRole("region", { name: "Runtime closure 상세" })).toBeInTheDocument();
  await waitFor(() => expect(onProjectionChange).toHaveBeenLastCalledWith(expect.objectContaining({ activeSource: "github", selectedContext: expect.objectContaining({ resourceIds: [issue.resource_id] }) })));
  fireEvent.click(screen.getByRole("tab", { name: /메일/ }));
  await waitFor(() => expect(onProjectionChange).toHaveBeenLastCalledWith(expect.objectContaining({ activeSource: "gmail", selectedContext: expect.objectContaining({ resourceIds: [] }) })));
  expect(screen.queryByText("Runtime closure")).not.toBeInTheDocument();

  rerender(<ResourceSidebar {...sidebarProps({ scopeKey: "session|github:disconnected", githubAccountId: null, githubConnected: false, onProjectionChange })} />);
  expect(screen.queryByRole("tab", { name: /GitHub Issues/ })).not.toBeInTheDocument();
  expect(screen.getByRole("tab", { name: /메일/ })).toHaveAttribute("aria-selected", "true");
  await waitFor(() => expect(onProjectionChange).toHaveBeenLastCalledWith(expect.objectContaining({ selectedContext: expect.objectContaining({ resourceIds: [] }) })));
});

test("복수 GitHub allowlist는 첫 저장소를 암묵적으로 조회하지 않고 명시적으로 선택한 저장소만 탐색한다", async () => {
  const issue: ResourceItem = {
    schema_version: 1,
    selection_handle: "github-selection",
    source: "github",
    resource_type: "github_issue",
    resource_id: "solar-ai-dev/google-work-agent#205",
    parent_id: "solar-ai-dev/google-work-agent",
    title: "GitHub repository access",
    link_url: "https://github.com/solar-ai-dev/google-work-agent/issues/205",
    version: "1",
    related_resource_ids: ["solar-ai-dev/google-work-agent"],
    metadata: { repository: "solar-ai-dev/google-work-agent", issue_number: 205, issue_state: "OPEN" },
  };
  const browse = mockBrowse().mockImplementation(async (request) => request.source === "github" && request.repository === "solar-ai-dev/google-work-agent"
    ? { ...emptyPage, items: [issue], total_count: 1 }
    : emptyPage);

  render(<ResourceSidebar {...sidebarProps({
    googleAccountId: null,
    githubAccountId: "github-account",
    googleConnected: false,
    githubConnected: true,
    githubRepositories: ["bonggyulim/search-save", "solar-ai-dev/google-work-agent"],
  })} />);

  const repositorySelect = screen.getByLabelText("조회할 GitHub Repository");
  expect(repositorySelect).toHaveValue("");
  expect(screen.getByText("탐색할 GitHub Repository를 선택해 주세요.")).toBeInTheDocument();
  expect(browse).not.toHaveBeenCalledWith(expect.objectContaining({ source: "github" }));

  fireEvent.change(repositorySelect, { target: { value: "solar-ai-dev/google-work-agent" } });
  expect(await screen.findByText("GitHub repository access")).toBeInTheDocument();
  expect(browse).toHaveBeenCalledWith(expect.objectContaining({ source: "github", repository: "solar-ai-dev/google-work-agent" }));

  fireEvent.change(repositorySelect, { target: { value: "bonggyulim/search-save" } });
  await waitFor(() => expect(screen.queryByText("GitHub repository access")).not.toBeInTheDocument());
  expect(browse).toHaveBeenCalledWith(expect.objectContaining({ source: "github", repository: "bonggyulim/search-save" }));
});
