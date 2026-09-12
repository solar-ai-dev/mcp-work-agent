import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { StartupCheckScreen } from "../../../src/features/diagnostics/startup_check";

test("shows readiness evidence and exposes retry only after failure", async () => {
  const retry = vi.fn();
  render(<StartupCheckScreen state={{ phase: "readiness", status: "error", message: "준비 실패", checks: [{ name: "sqlite", state: "NOT_READY", detail: "migration" }], error: "확인 필요", retryable: true }} onRetry={retry} />);

  expect(screen.getByText("sqlite")).toBeInTheDocument();
  expect(screen.getByText("migration")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "다시 확인" }));
  expect(retry).toHaveBeenCalledOnce();
});

test("stops without a retry control when the startup failure is not retryable", () => {
  render(<StartupCheckScreen state={{ phase: "failed", status: "error", message: "시작 검사 실패", checks: [], error: "안전한 실행 조건을 확인하지 못해 작업을 중단했습니다.", retryable: false }} onRetry={vi.fn()} />);

  expect(screen.getByText("안전한 실행 조건을 확인하지 못해 작업을 중단했습니다.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "다시 확인" })).not.toBeInTheDocument();
});
