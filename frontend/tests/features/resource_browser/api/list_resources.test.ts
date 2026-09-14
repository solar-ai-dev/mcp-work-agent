import { afterEach, expect, test, vi } from "vitest";
import { getResourceCount, listResources, listTaskLists } from "../../../../src/features/resource_browser/api/list_resources";

afterEach(() => vi.restoreAllMocks());

test("Task List discovery forwards opaque continuation and Tasks preserve future scheduled dates", async () => {
  const jsonResponse = { status: 200, headers: { "content-type": "application/json" } };
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(JSON.stringify({ schema_version: 1, items: [], next_page_token: null }), jsonResponse)).mockResolvedValueOnce(new Response(JSON.stringify({ schema_version: 1, items: [{ schema_version: 1, selection_handle: "handle", resource_id: "seed", title: "future task", task_status: "incomplete", scheduled_date: "2026-09-10", completed_at: null, tasklist_id: "new-list" }], next_page_token: null, total_count: 1, projection_version: "1" }), jsonResponse));
  await listTaskLists("opaque+next");
  expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/resources/task-lists?page_size=100&page_token=opaque%2Bnext");
  const result = await listResources({ source: "tasks", taskListId: "new-list" });
  expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/v1/resources/tasks?page_size=100&task_list_id=new-list");
  expect(result.items[0]).toEqual(expect.objectContaining({ parent_id: "new-list", metadata: expect.objectContaining({ scheduled_date: "2026-09-10", task_status: "incomplete" }) }));
});

test("listResources uses bounded source-specific Local API filters and opaque continuation", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
    schema_version: 1, items: [], next_page_token: null, total_count: null, projection_version: "1",
  }), { status: 200, headers: { "content-type": "application/json" } }));

  await listResources({ source: "gmail", query: " follow up ", continuation: "opaque-next", pageSize: 999, includeThreadMetadata: false });
  expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/resources/gmail?query=follow+up&page_size=100&page_token=opaque-next&include_thread_metadata=false");
});

test("listResources projects the exact #159 Gmail wire contract without stale aliases", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
    schema_version: 1,
    items: [{
      schema_version: 1,
      selection_handle: "opaque-handle",
      resource_id: "resource-1",
      subject: "Current subject",
      sender_name: "Sender",
      sender_email: "sender@example.com",
      received_at: "2026-08-31T00:00:00Z",
      snippet: "Current snippet",
      has_attachments: true,
    }],
    next_page_token: "opaque-next",
    total_count: null,
    projection_version: "7",
  }), { status: 200, headers: { "content-type": "application/json" } }));

  const response = await listResources({ source: "gmail", query: "" });

  expect(response.items).toEqual([expect.objectContaining({
    schema_version: 1,
    selection_handle: "opaque-handle",
    resource_id: "resource-1",
    source: "gmail",
    resource_type: "gmail_thread",
    title: "Current subject",
    version: "7",
    metadata: expect.objectContaining({
      sender_email: "sender@example.com",
      has_attachments: true,
    }),
  })]);
  expect(response.next_page_token).toBe("opaque-next");
  expect(response).not.toHaveProperty("api_contract_version");
});

test("resource count remains in the resource-browser API owner", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
    schema_version: 1, source: "gmail", exact_count: 3, as_of_ms: 1,
  }), { status: 200, headers: { "content-type": "application/json" } }));
  const response = await getResourceCount("gmail", { query: "in:inbox" });
  expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/resources/gmail/count?query=in%3Ainbox");
  expect(response.exact_count).toBe(3);
  expect(response).not.toHaveProperty("total_count");
});

test("GitHub Issues use the same resource browser transport and preserve selection identity", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
    schema_version: 1,
    items: [{
      schema_version: 1,
      selection_handle: "github-handle",
      resource_id: "solar-ai-dev/google-work-agent#181",
      repository: "solar-ai-dev/google-work-agent",
      issue_number: 181,
      title: "Runtime closure",
      description: "Connector Sidebar",
      issue_state: "OPEN",
      url: "https://github.com/solar-ai-dev/google-work-agent/issues/181",
      labels: ["product"],
      assignees: ["octocat"],
    }],
    next_page_token: null,
    total_count: 1,
    projection_version: "1",
  }), { status: 200, headers: { "content-type": "application/json" } }));

  const response = await listResources({ source: "github", repository: "solar-ai-dev/google-work-agent", issueState: "ALL" });

  expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/resources/github?repository=solar-ai-dev%2Fgoogle-work-agent&state=ALL");
  expect(response.items[0]).toEqual(expect.objectContaining({
    selection_handle: "github-handle",
    source: "github",
    resource_type: "github_issue",
    parent_id: "solar-ai-dev/google-work-agent",
    metadata: expect.objectContaining({ issue_number: 181, issue_state: "OPEN" }),
  }));
});
