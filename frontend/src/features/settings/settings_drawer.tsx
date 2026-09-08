import { useCallback, useEffect, useRef, useState } from "react";
import { ApiClientError } from "../../api/client";
import { DiagnosticsPanel, type RuntimeSummary } from "../diagnostics";
import { listCalendars, listTaskLists } from "../resource_browser/api/list_resources";
import type { CalendarContainer, TaskListContainer } from "../../api/contract";
import { disconnectGitHub, disconnectGoogle, getGitHubConnection, getGoogleConnection, startGitHubConnection, startGoogleConnection, type AuthorizationStart, type GitHubConnection, type GoogleConnection } from "./api/google_connection_operations";
import { getSettings, type SettingsView } from "./api/get_settings";
import { deleteLlmCredential, getLlmCredentialStatus, storeLlmCredential, type LlmCredentialStatus } from "./api/llm_credential_operations";
import { updateRuntimeMode, type RuntimeMode, type SelectableRuntimeMode } from "./api/update_runtime_mode";
import { updateSettings } from "./api/update_settings";
import { listRepositories, type RepositoryItem } from "./api/list_repositories";

const runtimeModeLabels: Record<RuntimeMode, string> = {
  AUTO: "선택 필요", LOCAL_GPU: "Local AI", API_LLM: "Gemini",
};
const connectionStatusLabels: Record<GoogleConnection["connection_status"], string> = {
  CONNECTING: "연결 중", CONNECTED: "연결됨", DISCONNECTED: "연결되지 않음",
  REAUTH_REQUIRED: "다시 로그인해야 합니다", UNAVAILABLE: "연결 상태를 확인할 수 없습니다",
};
const credentialValidationLabels: Record<LlmCredentialStatus["validation_status"], string> = {
  VALID: "확인됨", INVALID: "키를 확인해 주세요", UNAVAILABLE: "확인할 수 없음",
  NOT_CONFIGURED: "설정되지 않음",
};

function runtimeModeLabel(mode: string | null | undefined): string {
  if (mode === "MIXED") return "로컬·외부 모델 함께 사용";
  return mode && mode in runtimeModeLabels ? runtimeModeLabels[mode as RuntimeMode] : "확인 중";
}

function githubUnavailableMessage(connection: GitHubConnection): string | null {
  if (connection.connection_status !== "UNAVAILABLE") return null;
  if (connection.detail_code === "GITHUB_APP_CLIENT_ID_MISSING") {
    return "GitHub 연결 구성이 없습니다. 개발·배포 설정을 확인해 주세요.";
  }
  if (connection.detail_code === "KEYRING_UNAVAILABLE") {
    return "이 PC의 안전한 자격증명 저장소를 사용할 수 없습니다. 시스템 상태를 확인해 주세요.";
  }
  return "GitHub 연결 상태를 확인하지 못했습니다. 잠시 후 다시 확인해 주세요.";
}

function githubStatusFailureMessage(error: unknown): string {
  if (!(error instanceof ApiClientError)) {
    return "GitHub 연결 상태를 확인하지 못했습니다. 잠시 후 다시 확인해 주세요.";
  }
  const errorCode = error.envelope?.error_code;
  if (errorCode === "CONFIGURATION_ERROR") {
    return error.envelope?.detail_code === "GITHUB_APP_CLIENT_ID_MISSING"
      ? "GitHub 연결 구성이 없습니다. 개발·배포 설정을 확인해 주세요."
      : "GitHub 연결 구성이 올바르지 않습니다. 개발·배포 설정을 확인해 주세요.";
  }
  if (errorCode === "AUTH_REQUIRED") {
    return "GitHub 인증이 만료되었거나 유효하지 않습니다. 다시 연결해 주세요.";
  }
  if (errorCode === "PERMISSION_DENIED") {
    return "GitHub 계정 또는 Repository 접근 권한을 확인해 주세요.";
  }
  return "GitHub 서비스의 연결 상태를 확인하지 못했습니다. 잠시 후 다시 확인해 주세요.";
}

type Props = {
  runtime: RuntimeSummary | null;
  theme: string;
  onThemeChange: (theme: string) => void;
  onClose: () => void;
  onOperationalStateChanged: () => Promise<void>;
};

export function SettingsDrawer({ runtime, theme, onThemeChange, onClose, onOperationalStateChanged }: Props): JSX.Element {
  const [tab, setTab] = useState<"connections" | "ai" | "general">("connections");
  const [settings, setSettings] = useState<SettingsView | null>(null);
  const [google, setGoogle] = useState<GoogleConnection | null>(null);
  const [github, setGitHub] = useState<GitHubConnection | null>(null);
  const [githubStatusError, setGitHubStatusError] = useState<string | null>(null);
  const [githubAuthorization, setGitHubAuthorization] = useState<AuthorizationStart | null>(null);
  const [repositories, setRepositories] = useState<RepositoryItem[]>([]);
  const [repositoryError, setRepositoryError] = useState<string | null>(null);
  const [repositoryLoading, setRepositoryLoading] = useState(false);
  const [selectedRepositories, setSelectedRepositories] = useState<string[]>([]);
  const [selectedLocalModelId, setSelectedLocalModelId] = useState<string | null>(
    runtime?.local_models.find((model) => model.selected)?.model_id ?? null,
  );
  const [googleInventoryError, setGoogleInventoryError] = useState<string | null>(null);
  const repositoryRequest = useRef(0);
  const [credential, setCredential] = useState<LlmCredentialStatus | null>(null);
  const [taskLists, setTaskLists] = useState<TaskListContainer[]>([]);
  const [calendars, setCalendars] = useState<CalendarContainer[]>([]);
  const [apiKey, setApiKey] = useState("");
  const [storageMode, setStorageMode] = useState<"KEYRING" | "SESSION_ONLY">("KEYRING");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const commandIds = useRef(new Map<string, string>());

  const load = useCallback(async (): Promise<void> => {
    const [nextSettings, nextGoogle, nextGitHub, nextCredential, nextTaskLists, nextCalendars] = await Promise.allSettled([
      getSettings(), getGoogleConnection(), getGitHubConnection(), getLlmCredentialStatus(),
      loadContainerPages((cursor) => listTaskLists(cursor, true)),
      loadContainerPages((cursor) => listCalendars(cursor, true)),
    ]);
    if (nextSettings.status === "fulfilled") {
      const value = nextSettings.value;
      setSettings({ ...value, timezone: "Asia/Seoul",
        selected_calendar_ids: value.selected_calendar_ids ?? [],
        selected_tasklist_ids: value.selected_tasklist_ids ?? [],
      });
      setSelectedRepositories(value.selected_github_repositories?.map((item) => item.repository)
        ?? []);
    }
    if (nextGoogle.status === "fulfilled") setGoogle(nextGoogle.value);
    if (nextGitHub.status === "fulfilled") {
      setGitHub(nextGitHub.value);
      setGitHubStatusError(null);
    } else {
      setGitHub(null);
      setGitHubStatusError(githubStatusFailureMessage(nextGitHub.reason));
    }
    if (nextCredential.status === "fulfilled") setCredential(nextCredential.value);
    setTaskLists(nextTaskLists.status === "fulfilled" ? nextTaskLists.value : []);
    setCalendars(nextCalendars.status === "fulfilled" ? nextCalendars.value : []);
    setGoogleInventoryError(nextTaskLists.status === "rejected" || nextCalendars.status === "rejected" ? "사용 가능한 자료 목록을 확인하지 못했습니다. 연결 상태를 확인하고 새로고침해 주세요." : null);
    if ([nextSettings, nextGoogle, nextGitHub, nextCredential, nextTaskLists, nextCalendars].every((result) => result.status === "rejected")) {
      throw nextSettings.status === "rejected" ? nextSettings.reason : new Error("Settings unavailable");
    }
  }, []);

  const refreshRepositories = useCallback(async (): Promise<void> => {
    const requestId = ++repositoryRequest.current;
    setRepositoryLoading(true);
    setRepositoryError(null);
    try {
      const items = await loadRepositoryPages(github?.account_id ?? null);
      if (requestId !== repositoryRequest.current) return;
      setRepositories(items);
    } catch {
      if (requestId === repositoryRequest.current) {
        setRepositories([]);
        setRepositoryError("Repository 목록을 확인하지 못했습니다. GitHub 연결과 Repository 접근 권한을 확인해 주세요.");
      }
    } finally {
      if (requestId === repositoryRequest.current) setRepositoryLoading(false);
    }
  }, [github?.account_id]);

  useEffect(() => {
    if (github?.connection_status === "CONNECTED") void refreshRepositories();
    else setRepositories([]);
    return () => { repositoryRequest.current += 1; };
  }, [github?.connection_status, refreshRepositories]);

  useEffect(() => {
    void load().catch((error: unknown) => setMessage(errorMessage(error, "설정 정보를 불러오지 못했습니다.")));
  }, [load]);

  useEffect(() => {
    setSelectedLocalModelId(
      runtime?.local_models.find((model) => model.selected)?.model_id ?? null,
    );
  }, [runtime?.local_models]);

  useEffect(() => {
    let refreshing = false;
    let disposed = false;
    const refreshAfterReturn = (): void => {
      if (document.visibilityState !== "visible" || busy || githubAuthorization || refreshing) return;
      refreshing = true;
      void getGitHubConnection().then(async (connection) => {
        if (disposed) return;
        setGitHub(connection);
        setGitHubStatusError(null);
        if (connection.connection_status === "CONNECTED" && connection.account_id === github?.account_id) {
          await refreshRepositories();
        }
      }).catch((error: unknown) => {
        if (!disposed) setGitHubStatusError(githubStatusFailureMessage(error));
      }).finally(() => { refreshing = false; });
    };
    window.addEventListener("focus", refreshAfterReturn);
    document.addEventListener("visibilitychange", refreshAfterReturn);
    return () => {
      disposed = true;
      window.removeEventListener("focus", refreshAfterReturn);
      document.removeEventListener("visibilitychange", refreshAfterReturn);
    };
  }, [busy, github?.account_id, githubAuthorization, refreshRepositories]);

  useEffect(() => {
    if (github?.connection_status === "CONNECTED" || (!githubAuthorization && github?.connection_status !== "CONNECTING")) return;
    const intervalMs = Math.max(1, githubAuthorization?.poll_interval_seconds ?? 5) * 1000;
    let polling = false;
    let disposed = false;
    const timer = window.setInterval(() => {
      if (polling) return;
      if (githubAuthorization?.expires_at_ms && Date.now() >= githubAuthorization.expires_at_ms) {
        window.clearInterval(timer);
        setGitHubAuthorization(null);
        setMessage("GitHub 인증 코드가 만료되었습니다. 연결을 다시 시작해 주세요.");
        return;
      }
      polling = true;
      void getGitHubConnection().then((connection) => {
        if (disposed) return;
        setGitHub(connection);
        setGitHubStatusError(null);
        if (connection.authorization_status === "DENIED" || connection.authorization_status === "EXPIRED") {
          setGitHubAuthorization(null);
          setMessage(connection.authorization_status === "DENIED" ? "GitHub 인증이 거부되었습니다. 연결을 다시 시작할 수 있습니다." : "GitHub 인증 코드가 만료되었습니다. 연결을 다시 시작해 주세요.");
          return;
        }
        if (connection.connection_status === "CONNECTED") {
          setGitHubAuthorization(null);
          setMessage("GitHub 연결이 완료되었습니다. 접근 가능한 Repository를 확인합니다.");
          void onOperationalStateChanged().catch(() => setMessage("GitHub는 연결됐지만 화면 상태를 새로 확인하지 못했습니다. 설정을 다시 열어 주세요."));
        }
      }).catch(() => { if (!disposed) setMessage("GitHub 인증 상태를 확인하지 못했습니다. 연결을 확인한 뒤 다시 시도해 주세요."); }).finally(() => { polling = false; });
    }, intervalMs);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [github?.connection_status, githubAuthorization, onOperationalStateChanged]);

  function commandIdFor(operation: string): string {
    let commandId = commandIds.current.get(operation);
    if (!commandId) {
      commandId = crypto.randomUUID();
      commandIds.current.set(operation, commandId);
    }
    return commandId;
  }

  async function testGeminiConnection(): Promise<void> {
    setBusy(true);
    setMessage(null);
    try {
      const status = await getLlmCredentialStatus();
      setCredential(status);
      setMessage(`Gemini API: ${credentialValidationLabels[status.validation_status]}`);
    } catch (error) {
      setCredential(null);
      setMessage(errorMessage(error, "Gemini API 연결 상태를 확인하지 못했습니다."));
    } finally {
      setBusy(false);
    }
  }

  async function run(operation: string, action: (commandId: string) => Promise<void>, success: string, clearSecret = false): Promise<void> {
    setBusy(true);
    setMessage(null);
    try {
      await action(commandIdFor(operation));
      commandIds.current.delete(operation);
      await Promise.all([load(), onOperationalStateChanged()]);
      setMessage(success);
    } catch (error) {
      await Promise.allSettled([load(), onOperationalStateChanged()]);
      setMessage(errorMessage(error, "작업을 완료하지 못했습니다."));
    } finally {
      if (clearSecret) setApiKey("");
      setBusy(false);
    }
  }

  async function saveSettings(): Promise<void> {
    if (!settings) return;
    if (settings.preferred_llm_mode === "AUTO") {
      setMessage("Local AI 또는 Gemini 실행 방식을 선택해 주세요.");
      return;
    }
    const selectedRuntimeMode = settings.preferred_llm_mode;
    await run(`settings:update:${JSON.stringify([tab, selectedRuntimeMode, settings.external_llm_consent, settings.working_day_start_local, settings.working_day_end_local, settings.include_weekends, settings.calendar_buffer_minutes, settings.retention_days])}`, async (commandId) => {
      const updated = await updateSettings(commandId, {
        timezone: settings.timezone,
        preferred_llm_mode: selectedRuntimeMode,
        external_llm_consent: settings.external_llm_consent,
        retention_days: settings.retention_days,
        working_day_start_local: settings.working_day_start_local,
        working_day_end_local: settings.working_day_end_local,
        include_weekends: settings.include_weekends,
        calendar_buffer_minutes: settings.calendar_buffer_minutes,
      });
      setSettings(updated);
      if (tab === "ai" && selectedRuntimeMode !== runtime?.runtime_mode.requested_mode) {
        const operation = `runtime:${selectedRuntimeMode}`;
        await updateRuntimeMode(commandIdFor(operation), selectedRuntimeMode);
        commandIds.current.delete(operation);
      }
    }, "설정을 저장했습니다.");
  }

  function patch<K extends keyof SettingsView>(key: K, value: SettingsView[K]): void {
    setSettings((current) => current ? { ...current, [key]: value } : current);
  }

  function close(): void {
    setApiKey("");
    onClose();
  }

  const runtimeModes = availableRuntimeModes(runtime?.deployment_profile);
  const productLocalModels = runtime?.local_models?.filter((model) => ["qwen3.5:9b", "qwen3.5:4b"].includes(model.model_id)) ?? [];

  return (
    <aside className="drawer settings-drawer" aria-label="설정 및 진단">
      <div className="panel-header"><div><strong>설정</strong><p className="muted">연결할 자료와 작업 환경을 관리하세요.</p></div><button className="button-secondary" type="button" onClick={close}>닫기</button></div>
      <div className="settings-tabs" role="tablist" aria-label="설정 분류">
        {([ ["connections", "계정 및 연결"], ["ai", "AI"], ["general", "일반"] ] as const).map(([id, label]) => <button key={id} id={`settings-tab-${id}`} type="button" role="tab" aria-selected={tab === id} aria-controls={`settings-panel-${id}`} onClick={() => setTab(id)}>{label}</button>)}
      </div>
      <div className="panel-body">
        {message ? <p role="status" className="status-warn">{message}</p> : null}
        <div role="tabpanel" id="settings-panel-connections" aria-labelledby="settings-tab-connections" hidden={tab !== "connections"}>
        <section className="info-card" aria-label="Google 연결">
          <strong>Google Workspace</strong><p>{google ? connectionStatusLabels[google.connection_status] : "확인 중"}</p>
          {google?.display_email ? <p>{google.display_email}</p> : null}
          {google?.missing_required_scopes.length ? <p className="status-warn">필요한 권한이 부족합니다. 재연결해 권한을 허용해 주세요.</p> : google?.connection_status === "CONNECTED" ? <p>필요 권한 확인됨</p> : null}
          {settings ? <>
            <p className="muted">앱에서 사용할 자료를 선택하세요. 여러 개를 선택할 수 있습니다.</p>
            <fieldset className="settings-selection" disabled={busy || google?.connection_status !== "CONNECTED"}><legend>캘린더</legend>
              {calendars.map((item) => <label key={item.calendar_id}><input type="checkbox" checked={settings.selected_calendar_ids?.includes(item.calendar_id) ?? false} onChange={(e) => patch("selected_calendar_ids", toggleValue(settings.selected_calendar_ids ?? [], item.calendar_id, e.target.checked))} /><span>{item.title}{item.primary ? " · 기본 캘린더" : ""}</span></label>)}
              {!calendars.length && !googleInventoryError ? <p className="muted">접근 가능한 캘린더가 없습니다.</p> : null}
            </fieldset>
            <fieldset className="settings-selection" disabled={busy || google?.connection_status !== "CONNECTED"}><legend>할일 목록</legend>
              {taskLists.map((item) => <label key={item.tasklist_id}><input type="checkbox" checked={settings.selected_tasklist_ids?.includes(item.tasklist_id) ?? false} onChange={(e) => patch("selected_tasklist_ids", toggleValue(settings.selected_tasklist_ids ?? [], item.tasklist_id, e.target.checked))} /><span>{item.title}</span></label>)}
              {!taskLists.length && !googleInventoryError ? <p className="muted">접근 가능한 할일 목록이 없습니다.</p> : null}
            </fieldset>
            {googleInventoryError && google?.connection_status === "CONNECTED" ? <p role="alert" className="status-warn">{googleInventoryError}</p> : null}
            <div className="button-row"><button type="button" className="button-primary" disabled={busy || Boolean(googleInventoryError) || google?.connection_status !== "CONNECTED"} onClick={() => void run(`settings:google:${JSON.stringify([settings.selected_calendar_ids, settings.selected_tasklist_ids])}`, async (id) => { await updateSettings(id, { selected_calendar_ids: settings.selected_calendar_ids ?? [], selected_tasklist_ids: settings.selected_tasklist_ids ?? [] }); }, "사용할 Google 자료를 저장했습니다.")}>Google 자료 선택 저장</button><button type="button" className="button-secondary" disabled={busy} onClick={() => void run("settings:refresh", async () => {}, "자료 목록을 새로고침했습니다.")}>목록 새로고침</button></div>
          </> : null}
          <div className="button-row">
            {google?.connection_status !== "CONNECTED" ? <button type="button" className="button-primary" disabled={busy} onClick={() => void run("google:connect", async (id) => { const result = await startGoogleConnection(id); window.open(requireOAuthUrl(result.authorization_url), "_blank", "noopener,noreferrer"); }, "Google 연결 완료를 기다리고 있습니다.")}>연결</button> : null}
            {google?.connection_status === "CONNECTED" ? <button type="button" className="button-danger" disabled={busy} onClick={() => void run("google:disconnect", async (id) => { await disconnectGoogle(id); }, "Google 연결을 해제했습니다.")}>연결 해제</button> : null}
            {google?.connection_status === "CONNECTED" ? <button type="button" className="button-secondary" disabled={busy} onClick={() => void run("google:reconnect", async (id) => { const result = await startGoogleConnection(id); window.open(requireOAuthUrl(result.authorization_url), "_blank", "noopener,noreferrer"); }, "Google 재연결 인증을 기다리고 있습니다.")}>재연결</button> : null}
          </div>
        </section>
        <section className="info-card" aria-label="GitHub 연결">
          <strong>GitHub</strong>
          <p>{github ? connectionStatusLabels[github.connection_status] : githubStatusError ? "연결 상태를 확인할 수 없습니다" : "확인 중"}</p>
          {github?.display_email ? <p>{github.display_email}</p> : null}
          {github?.connection_status !== "CONNECTED" ? <p>GitHub를 연결하면 접근 가능한 Repository의 Issue를 조회하고 관리할 수 있습니다.</p> : <p>Repository 접근 범위는 GitHub App 설치 권한에 따릅니다.</p>}
          {githubStatusError ? <p className="status-warn">{githubStatusError}</p> : github?.connection_status === "UNAVAILABLE" ? <p className="status-warn">{githubUnavailableMessage(github)}</p> : null}
          {github?.missing_required_scopes.length ? <p className="status-warn">필요한 GitHub 권한이 부족합니다. 접근 설정을 확인해 주세요.</p> : null}
          {githubAuthorization?.flow_kind === "DEVICE_CODE" ? <div>
            <p>GitHub에 입력할 코드: <strong>{githubAuthorization.user_code}</strong></p>
            <p>GitHub 인증을 기다리고 있습니다.</p>
            <button type="button" className="button-secondary" onClick={() => { void navigator.clipboard.writeText(githubAuthorization.user_code ?? "").then(() => setMessage("인증 코드를 복사했습니다.")).catch(() => setMessage("복사하지 못했습니다. 표시된 코드를 직접 입력해 주세요.")); }}>코드 복사</button>
            {githubAuthorization.expires_at_ms ? <p>만료: {new Date(githubAuthorization.expires_at_ms).toLocaleString("ko-KR")}</p> : null}
            {githubAuthorization.verification_uri ? <button type="button" className="button-secondary" onClick={() => window.open(requireGitHubVerificationUrl(githubAuthorization.verification_uri!), "_blank", "noopener,noreferrer")}>GitHub 인증 페이지 열기</button> : null}
          </div> : null}
          {settings ? <div>
            <fieldset className="settings-selection" disabled={busy || github?.connection_status !== "CONNECTED" || repositoryLoading}><legend>사용할 저장소 · {selectedRepositories.length}개 선택</legend>
              {repositories.map((item) => <label key={item.repository_id}><input type="checkbox" checked={selectedRepositories.includes(item.repository)} onChange={(e) => setSelectedRepositories(toggleValue(selectedRepositories, item.repository, e.target.checked))} /><span>{item.repository}{item.private ? <small>비공개</small> : null}</span></label>)}
              {selectedRepositories.filter((name) => !repositories.some((item) => item.repository === name)).map((name) => <label key={name}><input type="checkbox" checked onChange={() => setSelectedRepositories(selectedRepositories.filter((value) => value !== name))} /><span>{name}<small>접근 재확인 필요</small></span></label>)}
            </fieldset>
            {repositoryError ? <p role="alert" className="status-warn">{repositoryError}</p> : github?.connection_status === "CONNECTED" && !repositoryLoading && repositories.length === 0 ? <p>접근 가능한 Repository가 없습니다. 접근 관리에서 설치 범위를 확인해 주세요.</p> : null}
            {repositoryLoading ? <p>Repository 접근 권한을 확인하고 있습니다.</p> : null}
            <div className="button-row">
              <button type="button" className="button-primary" disabled={busy || repositoryLoading || github?.connection_status !== "CONNECTED"} onClick={() => void run(`github:repositories:${JSON.stringify(selectedRepositories)}`, async (id) => { await updateSettings(id, { selected_github_repositories: selectedRepositories }); }, "사용할 저장소를 저장했습니다.")}>저장소 선택 저장</button>
              <button type="button" className="button-secondary" disabled={busy || !selectedRepositories.length} onClick={() => setSelectedRepositories([])}>모두 해제</button>
              <button type="button" className="button-secondary" disabled={repositoryLoading || github?.connection_status !== "CONNECTED"} onClick={() => void refreshRepositories()}>Repository 새로고침</button>
              <a className="button-secondary" href="https://github.com/settings/installations" target="_blank" rel="noreferrer">Repository 접근 관리</a>
            </div>
          </div> : null}
          <div className="button-row">
            {github?.connection_status !== "CONNECTED" ? <button type="button" className="button-primary" disabled={busy || github === null || github.connection_status === "UNAVAILABLE"} onClick={() => void run("github:connect", async (id) => { const result = await startGitHubConnection(id); setGitHubAuthorization(result); window.open(requireGitHubVerificationUrl(result.verification_uri ?? result.authorization_url), "_blank", "noopener,noreferrer"); }, github?.connection_status === "REAUTH_REQUIRED" ? "GitHub 재인증을 시작했습니다." : "GitHub 연결을 시작했습니다.")}>{github?.connection_status === "REAUTH_REQUIRED" ? "재연결" : "연결"}</button> : null}
            {github?.connection_status === "CONNECTED" ? <button type="button" className="button-danger" disabled={busy} onClick={() => void run("github:disconnect", async (id) => { await disconnectGitHub(id); setGitHubAuthorization(null); }, "GitHub 연결을 해제했습니다.")}>연결 해제</button> : null}
            {github?.connection_status === "CONNECTED" ? <button type="button" className="button-secondary" disabled={busy} onClick={() => void run("github:reconnect", async (id) => { setGitHubAuthorization(await startGitHubConnection(id)); }, "GitHub 재연결 인증을 기다리고 있습니다.")}>재연결</button> : null}
          </div>
        </section>
        </div>
        <div role="tabpanel" id="settings-panel-ai" aria-labelledby="settings-tab-ai" hidden={tab !== "ai"}>
        <section className="info-card" aria-label="Gemini API">
          <strong>Gemini API</strong><p>{credential === null ? "연결 상태를 확인할 수 없습니다" : credential.configured ? `${credential.storage_mode === "KEYRING" ? "PC에 안전하게 저장" : "이번 실행에서만 사용"} / ${credentialValidationLabels[credential.validation_status]}` : "설정되지 않음"}</p>
          <label>저장 방식<select value={storageMode} onChange={(e) => setStorageMode(e.target.value === "SESSION_ONLY" ? "SESSION_ONLY" : "KEYRING")}><option value="KEYRING">PC에 안전하게 저장</option><option value="SESSION_ONLY">이번 실행에서만 사용</option></select></label>
          <label>API 키<input type="password" autoComplete="off" placeholder="Gemini API Key" value={apiKey} onChange={(e) => setApiKey(e.target.value)} /></label>
          <div className="button-row"><button type="button" className="button-primary" disabled={busy || !apiKey.trim()} onClick={() => void run("credential:store", async (id) => { await storeLlmCredential(id, apiKey, storageMode); }, "자격증명을 저장했습니다.", true)}>API 키 저장</button><button type="button" className="button-danger" disabled={busy} onClick={() => void run("credential:delete", async (id) => { await deleteLlmCredential(id); }, "자격증명을 삭제했습니다.", true)}>API 키 삭제</button><button type="button" className="button-secondary" disabled={busy} onClick={() => void testGeminiConnection()}>연결 테스트</button></div>
        </section>
        {settings ? <section className="info-card" aria-label="AI 실행 설정">
          <strong>AI 실행 방식</strong>
          <label>사용할 모델 실행 방식<select value={settings.preferred_llm_mode === "AUTO" ? "" : settings.preferred_llm_mode} onChange={(e) => patch("preferred_llm_mode", e.target.value as SelectableRuntimeMode)}>{settings.preferred_llm_mode === "AUTO" ? <option value="" disabled>실행 방식 선택</option> : null}{runtimeModes.map((mode) => <option key={mode} value={mode}>{runtimeModeLabels[mode]}</option>)}</select></label>
          <label className="settings-check"><input type="checkbox" checked={settings.external_llm_consent} onChange={(e) => patch("external_llm_consent", e.target.checked)} />외부 AI에 업무 내용 전송 허용</label>
          <p className="muted">현재 요청 방식: {runtimeModeLabel(runtime?.runtime_mode.requested_mode)} · 실제: {runtimeModeLabel(runtime?.runtime_mode.actual_runtime)}</p>
          <button type="button" className="button-primary" disabled={busy} onClick={() => void saveSettings()}>AI 설정 저장</button>
        </section> : null}
        {runtime?.deployment_profile === "LOCAL_CAPABLE" ? <section className="info-card" aria-label="로컬 AI 준비">
          <strong>로컬 AI</strong>
          <p className="muted">준비된 모델 하나를 선택하세요. 다음 작업부터 적용됩니다.</p>
          <fieldset className="settings-selection" disabled={busy}><legend>사용할 로컬 모델</legend>
            {productLocalModels.map((model) => <label key={model.model_id}><input type="radio" name="local-model" checked={selectedLocalModelId === model.model_id} disabled={!model.installed || !model.approved} onChange={() => void run(`settings:model:${model.model_id}`, async (id) => { await updateSettings(id, { preferred_local_model_id: model.model_id }); setSelectedLocalModelId(model.model_id); }, `${model.model_id} 모델을 선택했습니다.`)} /><span>{model.model_id}<small>{model.installed && model.approved ? "준비됨" : model.installed ? "사용 가능 여부 확인 필요" : "설치되지 않음"}</small></span></label>)}
          </fieldset>
          {runtime?.llm_providers?.some((provider) => provider.provider === "LOCAL_GPU" && provider.error_code?.startsWith("LOCAL_MODEL_INSPECTION_")) ? <p role="alert" className="status-warn">Ollama 모델 검사를 완료하지 못했습니다. Ollama 상태를 확인한 뒤 다시 검사해 주세요.</p> : !productLocalModels.length ? <p className="muted">아직 모델 상태를 확인하지 못했습니다.</p> : null}
          {productLocalModels.length > 0 && !productLocalModels.some((model) => model.installed && model.approved) ? <p role="status">사용 가능한 로컬 모델이 없습니다. 로컬 AI 요청은 실행할 수 없습니다.</p> : null}
          <button type="button" className="button-secondary" disabled={busy} onClick={() => void run("runtime:inspect", async () => {}, "로컬 모델 검사를 마쳤습니다.")}>모델 검사</button>
        </section> : null}
        </div>
        <div role="tabpanel" id="settings-panel-general" aria-labelledby="settings-tab-general" hidden={tab !== "general"}>
          <section className="info-card"><strong>화면</strong><label>테마<select aria-label="테마" value={theme} onChange={(e) => onThemeChange(e.target.value)}><option value="light">밝게</option><option value="dark">어둡게</option></select></label></section>
          {settings ? <section className="info-card" aria-label="작업 설정">
            <strong>업무 시간</strong>
            <div className="settings-row"><span>시간대</span><span>한국 · 서울 (UTC+9)</span></div>
            <label>업무 시작<input type="time" value={settings.working_day_start_local} onChange={(e) => patch("working_day_start_local", e.target.value)} /></label>
            <label>업무 종료<input type="time" value={settings.working_day_end_local} onChange={(e) => patch("working_day_end_local", e.target.value)} /></label>
            <label className="settings-check"><input type="checkbox" checked={settings.include_weekends} onChange={(e) => patch("include_weekends", e.target.checked)} />주말 포함</label>
            <label>일정 사이 여유 시간(분)<input type="number" min="0" value={settings.calendar_buffer_minutes} onChange={(e) => patch("calendar_buffer_minutes", Number(e.target.value))} /></label>
            <label>대화 보존 기간(일)<input type="number" min="1" max="30" value={settings.retention_days} onChange={(e) => patch("retention_days", Number(e.target.value))} /></label>
            <button type="button" className="button-primary" disabled={busy} onClick={() => void saveSettings()}>일반 설정 저장</button>
          </section> : null}
          <details className="settings-diagnostics"><summary>진단 및 복구</summary><DiagnosticsPanel runtime={runtime} onRefresh={onOperationalStateChanged} /></details>
        </div>
      </div>
    </aside>
  );
}

function availableRuntimeModes(profile: string | undefined): SelectableRuntimeMode[] {
  return profile === "LOCAL_CAPABLE" ? ["LOCAL_GPU", "API_LLM"] : ["API_LLM"];
}

function toggleValue(values: string[], value: string, checked: boolean): string[] {
  return checked ? [...new Set([...values, value])] : values.filter((item) => item !== value);
}

async function loadRepositoryPages(accountId: string | null): Promise<RepositoryItem[]> {
  if (!accountId) throw new Error("GitHub account is unavailable");
  const items = new Map<number, RepositoryItem>();
  const seen = new Set<string>();
  let cursor: string | undefined;
  for (let page = 0; page < 100; page += 1) {
    const result = await listRepositories(cursor);
    if (result.account_id !== accountId) throw new Error("GitHub account changed");
    result.items.forEach((item) => items.set(item.repository_id, item));
    cursor = result.next_cursor ?? undefined;
    if (!cursor) return [...items.values()];
    if (seen.has(cursor)) break;
    seen.add(cursor);
  }
  throw new Error("Repository 목록을 모두 확인하지 못했습니다.");
}

async function loadContainerPages<T>(fetchPage: (cursor: string | null) => Promise<{ items: T[]; next_page_token: string | null }>): Promise<T[]> {
  const items: T[] = [];
  const seen = new Set<string>();
  let cursor: string | null = null;
  for (let page = 0; page < 100; page += 1) {
    const result = await fetchPage(cursor);
    items.push(...result.items);
    cursor = result.next_page_token;
    if (!cursor) return items;
    if (seen.has(cursor)) break;
    seen.add(cursor);
  }
  throw new Error("자료 목록을 모두 확인하지 못했습니다.");
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiClientError ? error.message : fallback;
}

function requireOAuthUrl(value: string): string {
  const url = new URL(value);
  if (url.protocol !== "http:" || url.hostname !== "127.0.0.1" || !url.port || url.pathname !== "/oauth/authorize") throw new Error("Unexpected OAuth authorization URL");
  url.searchParams.set("return_to", new URL("/", window.location.origin).toString());
  return url.toString();
}

function requireGitHubVerificationUrl(value: string): string {
  const url = new URL(value);
  if (url.protocol !== "https:" || url.hostname !== "github.com") throw new Error("Unexpected GitHub verification URL");
  return url.toString();
}
