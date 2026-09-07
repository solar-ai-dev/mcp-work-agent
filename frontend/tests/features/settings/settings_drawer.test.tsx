import { render, screen, within, waitFor, fireEvent, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { SettingsDrawer } from "../../../src/features/settings/settings_drawer";
import * as settingsApi from "../../../src/features/settings/api/get_settings";
import * as googleApi from "../../../src/features/settings/api/google_connection_operations";
import * as credentialApi from "../../../src/features/settings/api/llm_credential_operations";
import * as resourceApi from "../../../src/features/resource_browser/api/list_resources";
import * as repositoryApi from "../../../src/features/settings/api/list_repositories";
import * as updateApi from "../../../src/features/settings/api/update_settings";

vi.mock("../../../src/features/settings/api/get_settings", () => ({ getSettings: vi.fn() }));
vi.mock("../../../src/features/settings/api/google_connection_operations", () => ({ getGoogleConnection: vi.fn(), startGoogleConnection: vi.fn(), disconnectGoogle: vi.fn(), getGitHubConnection: vi.fn(), startGitHubConnection: vi.fn(), disconnectGitHub: vi.fn() }));
vi.mock("../../../src/features/settings/api/llm_credential_operations", () => ({ getLlmCredentialStatus: vi.fn(), storeLlmCredential: vi.fn(), deleteLlmCredential: vi.fn() }));
vi.mock("../../../src/features/resource_browser/api/list_resources", () => ({ listTaskLists: vi.fn(), listCalendars: vi.fn() }));
vi.mock("../../../src/features/settings/api/update_settings", () => ({ updateSettings: vi.fn() }));
vi.mock("../../../src/features/settings/api/list_repositories", () => ({ listRepositories: vi.fn() }));
vi.mock("../../../src/features/settings/api/update_runtime_mode", () => ({ updateRuntimeMode: vi.fn() }));

beforeEach(() => {
  vi.mocked(credentialApi.getLlmCredentialStatus).mockResolvedValue({ schema_version: 1, provider: "gemini", configured: false, storage_mode: null, validation_status: "NOT_CONFIGURED" });
  vi.mocked(resourceApi.listCalendars).mockResolvedValue({ schema_version: 1, items: [], next_page_token: null });
  vi.mocked(resourceApi.listTaskLists).mockResolvedValue({ schema_version: 1, items: [], next_page_token: null });
  vi.mocked(googleApi.getGoogleConnection).mockResolvedValue({ schema_version: 1, connector_id: "google_workspace", account_id: null, display_email: null, connection_status: "DISCONNECTED", granted_scopes: [], missing_required_scopes: [] });
  vi.mocked(googleApi.getGitHubConnection).mockResolvedValue({ schema_version: 1, connector_id: "github", account_id: null, display_email: null, connection_status: "DISCONNECTED", granted_scopes: [], missing_required_scopes: [] });
});

test("Google 자료를 여러 개 선택하고 저장 후 다시 열어도 유지한다", async () => {
  let saved = { ...connectionSettings(), selected_tasklist_ids: ["one", "two", "three"], selected_calendar_ids: ["one", "two", "three"] };
  vi.mocked(settingsApi.getSettings).mockImplementation(async () => saved);
  vi.mocked(googleApi.getGoogleConnection).mockResolvedValue({ schema_version: 1, connector_id: "google_workspace", account_id: "google:1", display_email: "test@example.invalid", connection_status: "CONNECTED", granted_scopes: [], missing_required_scopes: [] });
  vi.mocked(googleApi.getGitHubConnection).mockResolvedValue({ schema_version: 1, connector_id: "github", account_id: null, display_email: null, connection_status: "DISCONNECTED", granted_scopes: [], missing_required_scopes: [] });
  vi.mocked(resourceApi.listTaskLists).mockResolvedValue({ schema_version: 1, items: ["one", "two", "three"].map((id) => ({ schema_version: 1, tasklist_id: id, title: `할일 ${id}` })), next_page_token: null });
  vi.mocked(resourceApi.listCalendars).mockResolvedValue({ schema_version: 1, items: ["one", "two", "three"].map((id) => ({ schema_version: 1, calendar_id: id, title: `일정 ${id}`, primary: false })), next_page_token: null });
  vi.mocked(updateApi.updateSettings).mockImplementation(async (_id, patch) => { saved = { ...saved, selected_tasklist_ids: patch.selected_tasklist_ids ?? [], selected_calendar_ids: patch.selected_calendar_ids ?? [] }; return saved; });
  const props = { runtime: null, theme: "light", onThemeChange: vi.fn(), onClose: vi.fn(), onOperationalStateChanged: vi.fn().mockResolvedValue(undefined) };
  const view = render(<SettingsDrawer {...props} />);
  await userEvent.click(await screen.findByRole("checkbox", { name: "할일 three" }));
  await userEvent.click(screen.getByRole("checkbox", { name: "일정 one" }));
  await userEvent.click(screen.getByRole("button", { name: "Google 자료 선택 저장" }));
  await waitFor(() => expect(saved.selected_tasklist_ids).toEqual(["one", "two"]));
  expect(saved.selected_calendar_ids).toEqual(["two", "three"]);
  expect(updateApi.updateSettings).toHaveBeenLastCalledWith(expect.any(String), { selected_tasklist_ids: ["one", "two"], selected_calendar_ids: ["two", "three"] });
  view.unmount();
  render(<SettingsDrawer {...props} />);
  expect(await screen.findByRole("checkbox", { name: "할일 one" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "할일 three" })).not.toBeChecked();
  expect(screen.getByRole("checkbox", { name: "일정 two" })).toBeChecked();
  expect(resourceApi.listTaskLists).toHaveBeenCalledWith(null, true);
});

test("준비된 9B와 4B 사이 선택을 기존 Settings API로 저장한다", async () => {
  let saved = { ...connectionSettings(), preferred_local_model_id: "qwen3.5:9b" };
  vi.mocked(settingsApi.getSettings).mockImplementation(async () => saved);
  vi.mocked(updateApi.updateSettings).mockImplementation(async (_id, patch) => { saved = { ...saved, preferred_local_model_id: patch.preferred_local_model_id! }; return saved; });
  const runtime = { deployment_profile: "LOCAL_CAPABLE", runtime_mode: { requested_mode: "LOCAL_GPU", actual_runtime: "LOCAL_GPU", fallback_reason: null }, local_models: ["qwen3.5:9b", "qwen3.5:4b"].map((model_id) => ({ schema_version: 1, model_id, installed: true, approved: true, selected: model_id.endsWith(":9b") })) } as never;
  render(<SettingsDrawer runtime={runtime} theme="light" onThemeChange={vi.fn()} onClose={vi.fn()} onOperationalStateChanged={vi.fn().mockResolvedValue(undefined)} />);
  await userEvent.click(screen.getByRole("tab", { name: "AI" }));
  const four = await screen.findByRole("radio", { name: /qwen3.5:4b/ });
  await userEvent.click(four);
  await waitFor(() => expect(four).toBeChecked());
  expect(updateApi.updateSettings).toHaveBeenLastCalledWith(expect.any(String), { preferred_local_model_id: "qwen3.5:4b" });
  await userEvent.click(screen.getByRole("radio", { name: /qwen3.5:9b/ }));
  await waitFor(() => expect(saved.preferred_local_model_id).toBe("qwen3.5:9b"));
});

test("SettingsDrawer loads typed non-secret settings, connection, credentials, and backup inventory", async () => {
  vi.mocked(settingsApi.getSettings).mockResolvedValue({ schema_version: 1, timezone: "Asia/Seoul", default_tasklist_id: null, default_calendar_id: null, preferred_llm_mode: "AUTO", external_llm_consent: false, retention_days: 30, theme: "LIGHT", panel_preferences: { schema_version: 1, right_panel_default_open: false, right_panel_default_tab: "CONVERSATIONS" }, working_day_start_local: "09:00", working_day_end_local: "18:00", include_weekends: false, calendar_buffer_minutes: 10, max_run_execution_ms: 1, max_connector_calls_per_run: 1, max_source_page_calls_per_run: 1, max_detail_fetches_per_run: 1, max_context_tokens_per_run: 1, max_retry_attempts_per_run: 1, circuit_failure_threshold: 1, circuit_open_duration_ms: 1 });
  vi.mocked(googleApi.getGoogleConnection).mockResolvedValue({ schema_version: 1, connector_id: "google", account_id: null, display_email: null, connection_status: "DISCONNECTED", granted_scopes: [], missing_required_scopes: [] });
  vi.mocked(googleApi.getGitHubConnection).mockResolvedValue({ schema_version: 1, connector_id: "github", account_id: null, display_email: null, connection_status: "DISCONNECTED", granted_scopes: [], missing_required_scopes: [] });
  vi.mocked(credentialApi.getLlmCredentialStatus).mockResolvedValue({ schema_version: 1, provider: "gemini", configured: false, storage_mode: null, validation_status: "NOT_CONFIGURED" });
  vi.mocked(resourceApi.listTaskLists).mockResolvedValue({ schema_version: 1, items: [{ schema_version: 1, tasklist_id: "tasks-1", title: "내 할 일" }], next_page_token: null });
  vi.mocked(resourceApi.listCalendars).mockResolvedValue({ schema_version: 1, items: [{ schema_version: 1, calendar_id: "calendar-1", title: "내 일정", primary: true }], next_page_token: null });
  render(<SettingsDrawer runtime={null} theme="light" onThemeChange={vi.fn()} onClose={vi.fn()} onOperationalStateChanged={vi.fn()} />);
  expect(await screen.findByLabelText("작업 설정")).toBeInTheDocument();
  expect(screen.getByLabelText("Gemini API").querySelector('input[type="password"]')).toHaveValue("");
  expect(document.body.textContent).not.toContain("sk-");
  await userEvent.click(screen.getByRole("tab", { name: "일반" }));
  expect(screen.getByRole("combobox", { name: "테마" })).toHaveValue("light");
  expect(screen.getByText("한국 · 서울 (UTC+9)")).toBeInTheDocument();
  expect(screen.queryByLabelText("시간대")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("tab", { name: "계정 및 연결" }));
  expect(within(screen.getByLabelText("Google 연결")).getByText("연결되지 않음")).toBeInTheDocument();
  expect(within(screen.getByLabelText("GitHub 연결")).getByText("연결되지 않음")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("tab", { name: "AI" }));
  expect(screen.getByRole("option", { name: "PC에 안전하게 저장" })).toHaveValue("KEYRING");
  expect(screen.getByRole("option", { name: "이번 실행에서만 사용" })).toHaveValue("SESSION_ONLY");
});

test("constrains API_ONLY mode choices without exposing process controls", async () => {
  vi.mocked(settingsApi.getSettings).mockResolvedValue({ schema_version: 1, timezone: "Asia/Seoul", default_tasklist_id: "tasks-1", default_calendar_id: "calendar-1", preferred_llm_mode: "API_LLM", external_llm_consent: true, retention_days: 30, theme: "LIGHT", panel_preferences: { schema_version: 1, right_panel_default_open: false, right_panel_default_tab: "CONVERSATIONS" }, working_day_start_local: "09:00", working_day_end_local: "18:00", include_weekends: false, calendar_buffer_minutes: 10, max_run_execution_ms: 1, max_connector_calls_per_run: 1, max_source_page_calls_per_run: 1, max_detail_fetches_per_run: 1, max_context_tokens_per_run: 1, max_retry_attempts_per_run: 1, circuit_failure_threshold: 1, circuit_open_duration_ms: 1 });
  vi.mocked(googleApi.getGoogleConnection).mockResolvedValue({ schema_version: 1, connector_id: "google", account_id: null, display_email: null, connection_status: "DISCONNECTED", granted_scopes: [], missing_required_scopes: [] });
  vi.mocked(googleApi.getGitHubConnection).mockResolvedValue({ schema_version: 1, connector_id: "github", account_id: null, display_email: null, connection_status: "DISCONNECTED", granted_scopes: [], missing_required_scopes: [] });
  vi.mocked(credentialApi.getLlmCredentialStatus).mockResolvedValue({ schema_version: 1, provider: "gemini", configured: false, storage_mode: null, validation_status: "NOT_CONFIGURED" });
  vi.mocked(resourceApi.listTaskLists).mockResolvedValue({ schema_version: 1, items: [], next_page_token: null });
  vi.mocked(resourceApi.listCalendars).mockResolvedValue({ schema_version: 1, items: [], next_page_token: null });
  render(<SettingsDrawer runtime={{ deployment_profile: "API_ONLY", runtime_mode: { requested_mode: "API_LLM", actual_runtime: "API_LLM", fallback_reason: null } } as never} theme="light" onThemeChange={vi.fn()} onClose={vi.fn()} onOperationalStateChanged={vi.fn()} />);
  const mode = await screen.findByLabelText("사용할 모델 실행 방식");
  expect([...mode.querySelectorAll("option")].map((option) => option.value)).toEqual(["API_LLM"]);
  expect(screen.queryByLabelText("로컬 AI 준비")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "안전하게 종료" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "백업 만들기" })).not.toBeInTheDocument();
});

test("준비된 로컬 모델만 선택할 수 있고 설치 안내는 표시하지 않는다", async () => {
  vi.mocked(settingsApi.getSettings).mockResolvedValue({ schema_version: 1, timezone: "Asia/Seoul", default_tasklist_id: null, default_calendar_id: null, preferred_llm_mode: "LOCAL_GPU", preferred_local_model_id: "legacy-model", external_llm_consent: false, retention_days: 30, theme: "LIGHT", panel_preferences: { schema_version: 1, right_panel_default_open: false, right_panel_default_tab: "CONVERSATIONS" }, working_day_start_local: "09:00", working_day_end_local: "18:00", include_weekends: false, calendar_buffer_minutes: 10, max_run_execution_ms: 1, max_connector_calls_per_run: 1, max_source_page_calls_per_run: 1, max_detail_fetches_per_run: 1, max_context_tokens_per_run: 1, max_retry_attempts_per_run: 1, circuit_failure_threshold: 1, circuit_open_duration_ms: 1 });
  vi.mocked(googleApi.getGoogleConnection).mockResolvedValue({ schema_version: 1, connector_id: "google", account_id: null, display_email: null, connection_status: "DISCONNECTED", granted_scopes: [], missing_required_scopes: [] });
  vi.mocked(credentialApi.getLlmCredentialStatus).mockResolvedValue({ schema_version: 1, provider: "gemini", configured: false, storage_mode: null, validation_status: "NOT_CONFIGURED" });
  vi.mocked(resourceApi.listTaskLists).mockResolvedValue({ schema_version: 1, items: [], next_page_token: null });
  vi.mocked(resourceApi.listCalendars).mockResolvedValue({ schema_version: 1, items: [], next_page_token: null });
  render(<SettingsDrawer runtime={{ deployment_profile: "LOCAL_CAPABLE", runtime_mode: { requested_mode: "LOCAL_GPU", actual_runtime: "LOCAL_GPU", fallback_reason: null }, local_models: [{ schema_version: 1, model_id: "qwen3.5:4b", installed: true, approved: true, selected: true }, { schema_version: 1, model_id: "qwen3.5:9b", installed: false, approved: true, selected: true }] } as never} theme="light" onThemeChange={vi.fn()} onClose={vi.fn()} onOperationalStateChanged={vi.fn()} />);

  const mode = await screen.findByLabelText("사용할 모델 실행 방식");
  expect([...mode.querySelectorAll("option")].map((option) => option.value)).toEqual(["AUTO", "LOCAL_GPU", "API_LLM"]);
  expect(screen.queryByLabelText("Local model")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("tab", { name: "AI" }));
  expect(screen.getByRole("radio", { name: /qwen3.5:4b/ })).toBeEnabled();
  expect(screen.getByRole("radio", { name: /qwen3.5:9b/ })).toBeDisabled();
  expect(screen.queryByRole("link", { name: /설치 안내/ })).not.toBeInTheDocument();
});

test("GitHub Device Flow 코드를 표시하고 검증 URL만 연다", async () => {
  vi.mocked(settingsApi.getSettings).mockRejectedValue(new Error("not relevant"));
  vi.mocked(googleApi.getGoogleConnection).mockResolvedValue({ schema_version: 1, connector_id: "google_workspace", account_id: null, display_email: null, connection_status: "DISCONNECTED", granted_scopes: [], missing_required_scopes: [] });
  vi.mocked(googleApi.getGitHubConnection).mockResolvedValue({ schema_version: 1, connector_id: "github", account_id: null, display_email: null, connection_status: "DISCONNECTED", granted_scopes: [], missing_required_scopes: [] });
  vi.mocked(googleApi.startGitHubConnection).mockResolvedValue({ schema_version: 1, authorization_url: "https://github.com/login/device", callback_id: "flow-1", flow_kind: "DEVICE_CODE", verification_uri: "https://github.com/login/device", user_code: "ABCD-EFGH", expires_at_ms: Date.now() + 60_000, poll_interval_seconds: 5 });
  vi.mocked(credentialApi.getLlmCredentialStatus).mockRejectedValue(new Error("not relevant"));
  vi.mocked(resourceApi.listTaskLists).mockRejectedValue(new Error("not relevant"));
  vi.mocked(resourceApi.listCalendars).mockRejectedValue(new Error("not relevant"));
  const opened = vi.spyOn(window, "open").mockImplementation(() => null);

  render(<SettingsDrawer runtime={null} theme="light" onThemeChange={vi.fn()} onClose={vi.fn()} onOperationalStateChanged={vi.fn().mockResolvedValue(undefined)} />);
  const github = await screen.findByLabelText("GitHub 연결");
  await userEvent.click(within(github).getByRole("button", { name: "연결" }));

  expect(await within(github).findByText("ABCD-EFGH")).toBeInTheDocument();
  expect(opened).toHaveBeenCalledWith("https://github.com/login/device", "_blank", "noopener,noreferrer");
  opened.mockRestore();
});

test("GitHub 연결 불가 원인을 구성과 상태 조회 실패로 구분한다", async () => {
  vi.mocked(settingsApi.getSettings).mockResolvedValue(connectionSettings());
  vi.mocked(googleApi.getGitHubConnection).mockResolvedValue({ schema_version: 1, connector_id: "github", account_id: null, display_email: null, connection_status: "UNAVAILABLE", granted_scopes: [], missing_required_scopes: [], detail_code: "GITHUB_APP_CLIENT_ID_MISSING" });
  const props = { runtime: null, theme: "light", onThemeChange: vi.fn(), onClose: vi.fn(), onOperationalStateChanged: vi.fn().mockResolvedValue(undefined) };
  const first = render(<SettingsDrawer {...props} />);
  const github = await screen.findByLabelText("GitHub 연결");

  expect(github).toHaveTextContent("GitHub 연결 구성이 없습니다");
  expect(within(github).getByRole("button", { name: "연결" })).toBeDisabled();

  first.unmount();
  vi.mocked(googleApi.getGitHubConnection).mockRejectedValue(new Error("transport failed"));
  render(<SettingsDrawer {...props} />);

  const failed = await screen.findByLabelText("GitHub 연결");
  expect(failed).toHaveTextContent("GitHub 연결 상태를 확인하지 못했습니다");
  expect(failed).not.toHaveTextContent("개발·배포 설정");
  expect(within(failed).getByRole("button", { name: "연결" })).toBeDisabled();
});

function connectionSettings(): settingsApi.SettingsView {
  return { schema_version: 1, timezone: "Asia/Seoul", default_tasklist_id: "tasks-1", default_calendar_id: "calendar-1", default_github_repository: null, preferred_llm_mode: "LOCAL_GPU", preferred_local_model_id: null, external_llm_consent: false, retention_days: 30, theme: "LIGHT", panel_preferences: { schema_version: 1, right_panel_default_open: false, right_panel_default_tab: "CONVERSATIONS" }, working_day_start_local: "09:00", working_day_end_local: "18:00", include_weekends: false, calendar_buffer_minutes: 0, max_run_execution_ms: 900000, max_connector_calls_per_run: 50, max_source_page_calls_per_run: 8, max_detail_fetches_per_run: 12, max_context_tokens_per_run: 16000, max_retry_attempts_per_run: 2, circuit_failure_threshold: 3, circuit_open_duration_ms: 30000 };
}

test("인증 중 설정을 다시 열어도 기존 Device Flow 확인을 이어간다", async () => {
  vi.mocked(googleApi.startGitHubConnection).mockClear();
  vi.mocked(settingsApi.getSettings).mockResolvedValue(connectionSettings());
  vi.mocked(googleApi.getGitHubConnection).mockResolvedValue({ schema_version: 1, connector_id: "github", account_id: null, display_email: null, connection_status: "CONNECTING", granted_scopes: [], missing_required_scopes: [], authorization_status: "PENDING" });
  const changed = vi.fn().mockResolvedValue(undefined);
  const view = render(<SettingsDrawer runtime={null} theme="light" onThemeChange={vi.fn()} onClose={vi.fn()} onOperationalStateChanged={changed} />);
  await waitFor(() => expect(screen.getByLabelText("GitHub 연결")).toHaveTextContent("연결 중"));
  vi.mocked(googleApi.getGitHubConnection).mockResolvedValue({ schema_version: 1, connector_id: "github", account_id: "github:1", display_email: "sample", connection_status: "CONNECTED", granted_scopes: [], missing_required_scopes: [], authorization_status: "APPROVED" });
  vi.mocked(repositoryApi.listRepositories).mockResolvedValue({ schema_version: 1, account_id: "github:1", items: [], next_cursor: null });
  await act(async () => { await new Promise((resolve) => window.setTimeout(resolve, 5100)); });
  expect(screen.getByLabelText("GitHub 연결")).toHaveTextContent("연결됨");
  expect(changed).toHaveBeenCalledOnce();
  expect(googleApi.startGitHubConnection).not.toHaveBeenCalled();
  view.unmount();
}, 10000);

test("Gemini 연결 테스트 실패를 숨기거나 이전 성공 상태로 표시하지 않는다", async () => {
  vi.mocked(settingsApi.getSettings).mockResolvedValue(connectionSettings());
  vi.mocked(credentialApi.getLlmCredentialStatus).mockResolvedValue({ schema_version: 1, provider: "gemini", configured: true, storage_mode: "KEYRING", validation_status: "VALID" });
  render(<SettingsDrawer runtime={null} theme="light" onThemeChange={vi.fn()} onClose={vi.fn()} onOperationalStateChanged={vi.fn()} />);
  const region = await screen.findByLabelText("Gemini API");
  await userEvent.click(screen.getByRole("tab", { name: "AI" }));
  await waitFor(() => expect(region).toHaveTextContent("확인됨"));
  vi.mocked(credentialApi.getLlmCredentialStatus).mockRejectedValueOnce(new Error("unavailable"));
  await userEvent.click(within(region).getByRole("button", { name: "연결 테스트" }));
  expect(await screen.findByText("Gemini API 연결 상태를 확인하지 못했습니다.")).toBeInTheDocument();
  expect(region).not.toHaveTextContent("확인됨");
  expect(region).toHaveTextContent("연결 상태를 확인할 수 없습니다");
  expect(region).not.toHaveTextContent("설정되지 않음");
});

test("저장소 다중 선택을 저장하고 해제해도 Google과 Gemini 설정은 독립적이다", async () => {
  let saved = connectionSettings();
  vi.mocked(settingsApi.getSettings).mockImplementation(async () => saved);
  vi.mocked(googleApi.getGitHubConnection).mockResolvedValue({ schema_version: 1, connector_id: "github", account_id: "github:1", display_email: "sample", connection_status: "CONNECTED", granted_scopes: [], missing_required_scopes: [] });
  vi.mocked(googleApi.getGoogleConnection).mockResolvedValue({ schema_version: 1, connector_id: "google_workspace", account_id: "google:1", display_email: "test@example.invalid", connection_status: "CONNECTED", granted_scopes: [], missing_required_scopes: [] });
  vi.mocked(credentialApi.getLlmCredentialStatus).mockResolvedValue({ schema_version: 1, provider: "gemini", configured: true, storage_mode: "KEYRING", validation_status: "VALID" });
  vi.mocked(repositoryApi.listRepositories).mockResolvedValue({ schema_version: 1, account_id: "github:1", items: [{ repository: "sample/project", repository_id: 2, private: true }], next_cursor: null });
  vi.mocked(updateApi.updateSettings).mockImplementation(async (_id, patch) => {
    saved = { ...saved, selected_github_repositories: patch.selected_github_repositories?.map((repository) => ({ repository, repository_id: 2, account_id: "github:1" })) ?? [] };
    return saved;
  });
  const view = render(<SettingsDrawer runtime={null} theme="light" onThemeChange={vi.fn()} onClose={vi.fn()} onOperationalStateChanged={vi.fn().mockResolvedValue(undefined)} />);
  await userEvent.click(await screen.findByRole("checkbox", { name: /sample\/project/ }));
  const repositoryCallsBeforeReturn = vi.mocked(repositoryApi.listRepositories).mock.calls.length;
  fireEvent(window, new Event("focus"));
  await waitFor(() => expect(vi.mocked(repositoryApi.listRepositories).mock.calls.length).toBeGreaterThan(repositoryCallsBeforeReturn));
  expect(screen.getByRole("checkbox", { name: /sample\/project/ })).toBeChecked();
  await userEvent.click(screen.getByRole("button", { name: "저장소 선택 저장" }));
  await waitFor(() => expect(saved.selected_github_repositories?.map((item) => item.repository)).toEqual(["sample/project"]));
  expect(updateApi.updateSettings).toHaveBeenLastCalledWith(expect.any(String), { selected_github_repositories: ["sample/project"] });
  expect(saved.default_calendar_id).toBe("calendar-1");
  expect(saved.default_tasklist_id).toBe("tasks-1");
  expect(screen.getByLabelText("Gemini API")).toHaveTextContent("확인됨");
  view.unmount();
  render(<SettingsDrawer runtime={null} theme="light" onThemeChange={vi.fn()} onClose={vi.fn()} onOperationalStateChanged={vi.fn().mockResolvedValue(undefined)} />);
  await waitFor(() => expect(screen.getByRole("checkbox", { name: /sample\/project/ })).toBeChecked());
  await userEvent.click(screen.getByRole("button", { name: "모두 해제" }));
  await userEvent.click(screen.getByRole("button", { name: "저장소 선택 저장" }));
  await waitFor(() => expect(saved.selected_github_repositories).toEqual([]));
  expect(updateApi.updateSettings).toHaveBeenLastCalledWith(expect.any(String), { selected_github_repositories: [] });
});

test("GitHub 저장소 목록__여러 설치 페이지__자동으로 모두 표시한다", async () => {
  vi.mocked(settingsApi.getSettings).mockResolvedValue(connectionSettings());
  vi.mocked(googleApi.getGitHubConnection).mockResolvedValue({ schema_version: 1, connector_id: "github", account_id: "github:1", display_email: "sample", connection_status: "CONNECTED", granted_scopes: [], missing_required_scopes: [] });
  const listRepositories = vi.mocked(repositoryApi.listRepositories);
  listRepositories.mockReset();
  listRepositories
    .mockResolvedValueOnce({ schema_version: 1, account_id: "github:1", items: [{ repository: "sample/personal", repository_id: 1, private: true }], next_cursor: "next-installation" })
    .mockResolvedValueOnce({ schema_version: 1, account_id: "github:1", items: [{ repository: "sample/team", repository_id: 2, private: false }], next_cursor: null });

  render(<SettingsDrawer runtime={null} theme="light" onThemeChange={vi.fn()} onClose={vi.fn()} onOperationalStateChanged={vi.fn().mockResolvedValue(undefined)} />);

  expect(await screen.findByRole("checkbox", { name: /sample\/personal/ })).toBeInTheDocument();
  expect(await screen.findByRole("checkbox", { name: /sample\/team/ })).toBeInTheDocument();
  expect(listRepositories).toHaveBeenNthCalledWith(1, undefined);
  expect(listRepositories).toHaveBeenNthCalledWith(2, "next-installation");
  expect(screen.queryByRole("button", { name: "Repository 더 보기" })).not.toBeInTheDocument();
});

test("Repository 권한 실패와 정상 빈 목록을 구분하고 새로고침한다", async () => {
  vi.mocked(settingsApi.getSettings).mockResolvedValue(connectionSettings());
  vi.mocked(googleApi.getGitHubConnection).mockResolvedValue({ schema_version: 1, connector_id: "github", account_id: "github:1", display_email: "sample", connection_status: "CONNECTED", granted_scopes: [], missing_required_scopes: [] });
  vi.mocked(repositoryApi.listRepositories).mockRejectedValueOnce(new Error("permission denied"));
  render(<SettingsDrawer runtime={null} theme="light" onThemeChange={vi.fn()} onClose={vi.fn()} onOperationalStateChanged={vi.fn().mockResolvedValue(undefined)} />);
  expect(await within(screen.getByLabelText("GitHub 연결")).findByRole("alert")).toHaveTextContent("접근 권한");
  expect(screen.queryByText(/현재 페이지에 접근 가능한 Repository가 없습니다/)).not.toBeInTheDocument();
  vi.mocked(repositoryApi.listRepositories).mockResolvedValue({ schema_version: 1, account_id: "github:1", items: [], next_cursor: null });
  await userEvent.click(screen.getByRole("button", { name: "Repository 새로고침" }));
  expect(await screen.findByText(/접근 가능한 Repository가 없습니다/)).toBeInTheDocument();
  expect(within(screen.getByLabelText("GitHub 연결")).queryByRole("alert")).not.toBeInTheDocument();
});
