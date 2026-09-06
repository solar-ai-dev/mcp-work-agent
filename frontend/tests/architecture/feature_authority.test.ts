import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, extname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

const FRONTEND_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const SOURCE_ROOT = join(FRONTEND_ROOT, "src");
const FEATURE_ROOT = join(SOURCE_ROOT, "features");
const FEATURE_TEST_ROOT = join(FRONTEND_ROOT, "tests", "features");

const FEATURE_OWNERS = [
  "approval",
  "attachment",
  "conversation",
  "diagnostics",
  "recovery",
  "resource_browser",
  "run",
  "settings",
];

function sourceFiles(root: string): string[] {
  return readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    const path = join(root, entry.name);
    return entry.isDirectory() ? sourceFiles(path) : [path];
  }).filter((path) => [".ts", ".tsx"].includes(extname(path)) && !path.endsWith(".test.ts") && !path.endsWith(".test.tsx"));
}

function testFiles(root: string): string[] {
  return readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    const path = join(root, entry.name);
    return entry.isDirectory() ? testFiles(path) : [path];
  }).filter((path) => path.endsWith(".test.ts") || path.endsWith(".test.tsx"));
}

describe("frontend canonical authority", () => {
  test("top-level feature owners equal the canonical closed set", () => {
    const actual = readdirSync(FEATURE_ROOT, { withFileTypes: true })
      .filter((entry) => entry.isDirectory() && sourceFiles(join(FEATURE_ROOT, entry.name)).length > 0)
      .map((entry) => entry.name)
      .sort();

    expect(actual).toEqual(FEATURE_OWNERS);
    expect(actual).not.toEqual(expect.arrayContaining(["gmail", "tasks", "calendar"]));
  });

  test("feature ownership is enforced from source and public entries without a documentation inventory", () => {
    for (const owner of FEATURE_OWNERS) {
      const publicEntry = join(FEATURE_ROOT, owner, "index.ts");
      const ownerTests = join(FEATURE_TEST_ROOT, owner);
      expect(existsSync(publicEntry), `${owner} public entry`).toBe(true);
      expect(existsSync(ownerTests), `${owner} test owner`).toBe(true);
      expect(testFiles(ownerTests).length, `${owner} test owner`).toBeGreaterThan(0);
      expect(readFileSync(publicEntry, "utf8"), `${owner} public entry`).not.toMatch(/from\s+["']\.\.\//);
    }

    const appSources = sourceFiles(join(SOURCE_ROOT, "app"));
    for (const path of appSources) {
      const imports = readFileSync(path, "utf8").matchAll(/from\s+["']\.\.\/features\/([^"']+)["']/g);
      for (const match of imports) {
        expect(match[1], `${path} imports a feature through its public entry`).not.toContain("/");
        expect(FEATURE_OWNERS, `${path} imports a registered feature owner`).toContain(match[1]);
      }
    }

    const forbiddenOwnerBuckets = new Set(["common", "manager", "managers", "service", "services", "utils"]);
    const directories = readdirSync(FEATURE_ROOT, { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name);
    expect(directories.filter((name) => forbiddenOwnerBuckets.has(name))).toEqual([]);
  });

  test("browser transport remains local and has no provider SDK or secret persistence authority", () => {
    const sources = sourceFiles(SOURCE_ROOT).map((path) => readFileSync(path, "utf8")).join("\n");

    expect(sources).not.toMatch(/from\s+["'](?:@google|googleapis|@modelcontextprotocol)\//);
    expect(sources).not.toMatch(/fetch\(\s*["']https?:\/\//);
    expect(sources).not.toMatch(/(?:localStorage|sessionStorage)\.setItem\([^\n]*(?:token|secret|api[_-]?key)/i);
    expect(sources).not.toMatch(/(?:ResourceRef|selection_handle)[^\n]*(?:localStorage|indexedDB)/);
    expect(sources).not.toMatch(/gwa\.(?:theme|shell-preferences)/);
  });
});
