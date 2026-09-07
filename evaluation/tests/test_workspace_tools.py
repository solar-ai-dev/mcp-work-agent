"""Tests of local document boundaries, not a Product test or a semantic grader."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

from check_workspace import check_workspace, heading_anchors
from export_materials import (
    ALLOWED_EMAIL_ADDRESSES,
    EMAIL_ADDRESS,
    LINK,
    export_to_file,
    extract_materials,
    outside_fence_lines,
    read_scenario,
    validate_material_emails,
)

SAMPLE = """# 업무 상황

## 서비스에 등록할 자료

제목: 업무 메일

```text
등록할 업무 내용
```

## 시험 질문과 확인 기준

### 질문 1 — CASE-CORE-001

**사용자 입력**

> 시험 질문

**평가자 확인 — 제품 입력에 넣지 않음**

평가자 정답은 외부에 올리지 않음
"""


def make_workspace(root: Path) -> Path:
    (root / "README.md").write_text("# 업무 원본\n", encoding="utf-8")
    (root / "datasets").mkdir()
    scenario = root / "datasets" / "업무.md"
    scenario.write_text(SAMPLE, encoding="utf-8")
    return scenario


class MaterialExtractionTests(unittest.TestCase):
    def test_only_materials_are_exported(self) -> None:
        value = extract_materials(SAMPLE)
        self.assertIn("등록할 업무 내용", value)
        self.assertNotIn("시험 질문", value)
        self.assertNotIn("평가자 정답", value)
        self.assertNotIn("CASE-CORE-001", value)

    def test_missing_boundary_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            extract_materials(SAMPLE.split("## 시험 질문과 확인 기준")[0])

    def test_duplicate_boundary_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            extract_materials(SAMPLE + "\n## 시험 질문과 확인 기준\n")

    def test_reversed_boundary_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            extract_materials("## 시험 질문과 확인 기준\n## 서비스에 등록할 자료\n내용")

    def test_empty_materials_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            extract_materials("## 서비스에 등록할 자료\n\n## 시험 질문과 확인 기준\n")

    def test_unclosed_fence_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            extract_materials(SAMPLE + "\n```text\n")

    def test_heading_inside_payload_is_not_a_boundary(self) -> None:
        changed = SAMPLE.replace("등록할 업무 내용", "## 시험 질문과 확인 기준\n등록할 업무 내용")
        self.assertIn("등록할 업무 내용", extract_materials(changed))
        self.assertNotIn("평가자 정답", extract_materials(changed))

    def test_shorter_fence_does_not_end_four_tick_payload(self) -> None:
        changed = SAMPLE.replace("```text\n등록할 업무 내용\n```",
            "````text\n```\n## 시험 질문과 확인 기준\n본문 끝\n````")
        result = extract_materials(changed)
        self.assertIn("본문 끝", result)
        self.assertNotIn("평가자 정답", result)

    def test_different_fence_character_does_not_close_payload(self) -> None:
        changed = SAMPLE.replace("등록할 업무 내용", "~~~\n## 시험 질문과 확인 기준\n자료")
        self.assertIn("자료", extract_materials(changed))

    def test_longer_closer_is_valid(self) -> None:
        self.assertNotIn("평가자 정답", extract_materials(SAMPLE.replace("\n```\n", "\n`````\n")))

    def test_tilde_long_fence(self) -> None:
        changed = SAMPLE.replace("```text\n등록할 업무 내용\n```", "~~~~text\n~~~\n자료\n~~~~")
        self.assertIn("자료", extract_materials(changed))

    def test_false_closer_with_text_is_not_a_closer(self) -> None:
        text = "```text\n``` not closed\n"
        with self.assertRaises(ValueError):
            outside_fence_lines(text)

    def test_three_space_indented_fence_is_recognized(self) -> None:
        changed = SAMPLE.replace("```text", "   ```text").replace("\n```\n", "\n   ```\n")
        self.assertIn("등록할 업무 내용", extract_materials(changed))

    def test_unfenced_evaluator_label_inside_materials_is_rejected(self) -> None:
        changed = SAMPLE.replace("제목: 업무 메일", "**평가자 확인 — 제품 입력에 넣지 않음**")
        with self.assertRaises(ValueError):
            extract_materials(changed)

    def test_unexpected_top_level_section_inside_materials_is_rejected(self) -> None:
        changed = SAMPLE.replace("제목: 업무 메일", "## 정답 설명")
        with self.assertRaises(ValueError):
            extract_materials(changed)

    def test_crlf_is_supported(self) -> None:
        self.assertIn("등록할 업무 내용", extract_materials(SAMPLE.replace("\n", "\r\n")))

    def test_read_scenario_rejects_prompt_and_non_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scenario = make_workspace(root)
            self.assertIn("등록할 업무 내용", read_scenario(scenario, root))
            prompt = root / "prompt.md"
            prompt.write_text(SAMPLE, encoding="utf-8")
            with self.assertRaises(ValueError):
                read_scenario(prompt, root)
            raw = root / "datasets" / "data.txt"
            raw.write_text(SAMPLE, encoding="utf-8")
            with self.assertRaises(ValueError):
                read_scenario(raw, root)

    def test_symlink_leaving_dataset_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_workspace(root)
            outside = root / "prompt.md"
            outside.write_text(SAMPLE, encoding="utf-8")
            link = root / "datasets" / "link.md"
            try:
                link.symlink_to(outside)
            except OSError:
                self.skipTest("Symlink creation unavailable")
            with self.assertRaises(ValueError):
                read_scenario(link, root)

    def test_output_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scenario = make_workspace(root)
            output = root / "자료.md"
            output.write_text("기존 작업", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                export_to_file(scenario, output, root)
            self.assertEqual("기존 작업", output.read_text(encoding="utf-8"))
            with self.assertRaises(FileExistsError):
                export_to_file(scenario, scenario, root)
            self.assertEqual(SAMPLE, scenario.read_text(encoding="utf-8"))

    def test_output_in_other_directory_keeps_attachment_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scenario = make_workspace(root)
            attachments = scenario.parent / "attachments"
            attachments.mkdir()
            attachment = attachments / "점검 자료.csv"
            attachment.write_bytes(b"a,b\r\n1,2\r\n")
            scenario.write_text(SAMPLE.replace("제목: 업무 메일",
                "제목: 업무 메일\n\n[첨부](attachments/점검%20자료.csv)"), encoding="utf-8")
            outdir = root / "out"
            outdir.mkdir()
            output = outdir / "자료.md"
            export_to_file(scenario, output, root)
            content = output.read_text(encoding="utf-8")
            targets = [m.group(1) for m in LINK.finditer(content)]
            self.assertEqual(1, len(targets))
            self.assertEqual(attachment, (outdir / unquote(urlsplit(targets[0]).path)).resolve())
            self.assertEqual(b"a,b\r\n1,2\r\n", attachment.read_bytes())
            self.assertNotIn("평가자 정답", content)

    def test_missing_attachment_refuses_export(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scenario = make_workspace(root)
            scenario.write_text(SAMPLE.replace("제목: 업무 메일", "[첨부](attachments/missing.csv)"), encoding="utf-8")
            output = root / "out.md"
            with self.assertRaises(FileNotFoundError):
                export_to_file(scenario, output, root)
            self.assertFalse(output.exists())

    def test_material_link_cannot_read_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            outer = Path(directory)
            root = outer / "workspace"
            root.mkdir()
            scenario = make_workspace(root)
            (outer / "secret.txt").write_text("private", encoding="utf-8")
            scenario.write_text(SAMPLE.replace("제목: 업무 메일", "[자료](../../secret.txt)"), encoding="utf-8")
            with self.assertRaises(ValueError):
                read_scenario(scenario, root)

    def test_link_like_text_in_payload_is_not_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scenario = make_workspace(root)
            scenario.write_text(SAMPLE.replace("등록할 업무 내용", "[비신뢰 본문](../../not-a-file)"), encoding="utf-8")
            self.assertIn("[비신뢰 본문](../../not-a-file)", read_scenario(scenario, root))


class WorkspaceTests(unittest.TestCase):
    def test_empty_or_missing_workspace_is_not_a_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(check_workspace(Path(directory)))
            self.assertTrue(check_workspace(Path(directory) / "missing"))

    def test_sample_workspace_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_workspace(root)
            self.assertEqual([], check_workspace(root))

    def test_broken_link_is_found(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_workspace(root)
            (root / "README.md").write_text("# 문서\n[없음](missing.md)\n", encoding="utf-8")
            self.assertTrue(any("broken local link" in x for x in check_workspace(root)))

    def test_parent_escape_is_found(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_workspace(root)
            (root / "README.md").write_text("# 문서\n[외부](../outside.md)\n", encoding="utf-8")
            self.assertTrue(any("leaves workspace" in x for x in check_workspace(root)))

    def test_existing_fragment_passes_and_missing_fragment_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_workspace(root)
            readme = root / "README.md"
            readme.write_text("# 문서\n## 준비\n[이동](#준비)\n", encoding="utf-8")
            self.assertEqual([], check_workspace(root))
            readme.write_text("# 문서\n[이동](#없는-절)\n", encoding="utf-8")
            self.assertTrue(any("broken heading anchor" in x for x in check_workspace(root)))

    def test_duplicate_heading_anchor_suffix(self) -> None:
        self.assertEqual({"문서", "준비", "준비-1"}, heading_anchors("# 문서\n## 준비\n## 준비\n"))

    def test_missing_evaluator_boundary_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scenario = make_workspace(root)
            scenario.write_text(SAMPLE.replace("**평가자 확인 — 제품 입력에 넣지 않음**", ""), encoding="utf-8")
            self.assertTrue(any("question/evaluator boundary" in x for x in check_workspace(root)))

    def test_repeated_question_number_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scenario = make_workspace(root)
            scenario.write_text(SAMPLE + SAMPLE[SAMPLE.index("### 질문"):], encoding="utf-8")
            self.assertTrue(any("question numbers" in x for x in check_workspace(root)))

    def test_repeated_case_identity_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scenario = make_workspace(root)
            (scenario.parent / "다른업무.md").write_text(SAMPLE, encoding="utf-8")
            self.assertTrue(any("duplicate question identity" in x for x in check_workspace(root)))

    def test_example_identity_inside_payload_is_not_a_second_case(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scenario = make_workspace(root)
            scenario.write_text(SAMPLE.replace("등록할 업무 내용", "### 질문 1 — CASE-CORE-001"), encoding="utf-8")
            self.assertEqual([], check_workspace(root))

    def test_non_utf8_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scenario = make_workspace(root)
            scenario.write_bytes(b"\xff\xfe")
            self.assertTrue(check_workspace(root))

    def test_internal_prompt_cannot_contain_dataset_case_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_workspace(root)
            prompts = root / "prompt_candidates" / "mcp-tool-use-2026-v1" / "sources"
            prompts.mkdir(parents=True)
            text = "# Candidate\n" + "\n".join(
                f"## {heading}\nCASE-CORE-001\n" for heading in
                ("Responsibility", "Input boundary", "Decision procedure", "Boundaries", "Output and repair"))
            (prompts / "candidate.md").write_text(text, encoding="utf-8")
            self.assertTrue(any("dataset identity" in x for x in check_workspace(root)))

    def test_current_workspace_has_no_structural_errors(self) -> None:
        self.assertEqual([], check_workspace(Path(__file__).resolve().parents[1]))

    def test_every_scenario_exports_without_evaluator_section(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for scenario in sorted((root / "datasets").glob("*.md")):
            with self.subTest(scenario=scenario.name):
                value = read_scenario(scenario, root)
                outside = "\n".join(line for _, line in outside_fence_lines(value))
                self.assertNotIn("## 시험 질문과 확인 기준", outside)
                self.assertNotIn("**평가자 확인", outside)
                self.assertNotIn("### 질문 ", outside)




class PromptPathContractTests(unittest.TestCase):
    """Packaging tests of the supplied Prompt assets; not a production/LLM test."""

    def _copy_prompt_workspace(self, root: Path) -> Path:
        import shutil
        source = Path(__file__).resolve().parents[1]
        target = root / "evaluation"
        target.mkdir()
        (target / "README.md").write_text("# Test workspace\n", encoding="utf-8")
        shutil.copytree(source / "prompt_candidates", target / "prompt_candidates")
        for name in ("prompt_candidate.py", "__init__.py"):
            shutil.copyfile(source / name, target / name)
        return target

    def test_packaged_prompts_pass_source_and_bundle_checks(self) -> None:
        from check_workspace import prompt_asset_errors
        self.assertEqual(prompt_asset_errors(Path(__file__).resolve().parents[1]), [])

    def test_changed_source_is_not_silently_accepted(self) -> None:
        from check_workspace import PROMPT_ROOT, prompt_asset_errors
        with tempfile.TemporaryDirectory() as tmp:
            root = self._copy_prompt_workspace(Path(tmp))
            source = root / PROMPT_ROOT / "sources/retrieval.select_evidence.md"
            source.write_text(source.read_text() + "Changed without rehash.\n", encoding="utf-8")
            self.assertTrue(any("hash mismatch" in e for e in prompt_asset_errors(root)))

    def test_missing_input_contract_fails(self) -> None:
        from check_workspace import LEGACY_ROOT, prompt_asset_errors
        with tempfile.TemporaryDirectory() as tmp:
            root = self._copy_prompt_workspace(Path(tmp))
            (root / LEGACY_ROOT / "contracts/prompt-runtime-input-contract-v3.json").unlink()
            self.assertTrue(any("input contract" in e for e in prompt_asset_errors(root)))

    def test_moved_assembled_file_fails(self) -> None:
        from check_workspace import LEGACY_ROOT, prompt_asset_errors
        with tempfile.TemporaryDirectory() as tmp:
            root = self._copy_prompt_workspace(Path(tmp))
            source = root / LEGACY_ROOT / "assembled-r8.6-sllm-decomposition/planning.compose_answer.md"
            source.rename(source.with_name("renamed.md"))
            self.assertTrue(prompt_asset_errors(root))

    def test_duplicate_relocated_prompt_root_fails(self) -> None:
        from check_workspace import prompt_asset_errors
        with tempfile.TemporaryDirectory() as tmp:
            root = self._copy_prompt_workspace(Path(tmp))
            (root / "prompts").mkdir()
            self.assertTrue(any("Duplicate moved" in e for e in prompt_asset_errors(root)))

    def test_activation_claim_is_rejected(self) -> None:
        import json
        from check_workspace import PROMPT_ROOT, prompt_asset_errors
        with tempfile.TemporaryDirectory() as tmp:
            root = self._copy_prompt_workspace(Path(tmp))
            path = root / PROMPT_ROOT / "candidate.json"
            obj = json.loads(path.read_text())
            obj["activation_evidence"]["node_dev_pass"] = True
            path.write_text(json.dumps(obj), encoding="utf-8")
            self.assertTrue(any("activation evidence" in e for e in prompt_asset_errors(root)))



class CandidateMaterializationTests(unittest.TestCase):
    """Test the materializer with synthetic manifests, NOT a live Product runtime."""

    def setUp(self) -> None:
        import shutil
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = Path(__file__).resolve().parents[1]
        self.candidate = self.root / "evaluation/prompt_candidates/mcp-tool-use-2026-v1"
        shutil.copytree(self.source / "prompt_candidates/mcp-tool-use-2026-v1", self.candidate)

    def _data(self):
        import json
        return json.loads((self.candidate / "candidate.json").read_text(encoding="utf-8"))

    def _save(self, data) -> None:
        import json
        from prompt_candidate import calculate_candidate_bundle_hash
        data["candidate_bundle_hash"] = calculate_candidate_bundle_hash(data)
        (self.candidate / "candidate.json").write_text(json.dumps(data), encoding="utf-8")

    def _base(self, *, extra: bool = False, mismatch: bool = False, missing: bool = False):
        import hashlib
        import json
        data = self._data()
        directory = self.root / Path(data["base_prompt_manifest"]).parent
        (directory / "sources").mkdir(parents=True)
        slots, entries = [], []
        for ident in [*data["sources"], *(["request_understanding.identify_temporal_scope"] if extra else [])]:
            body = f"Current Product bytes for {ident}\n".encode()
            (directory / f"sources/{ident}.md").write_bytes(body)
            slot = dict(prompt_slot_id=ident, runtime_node_id=ident,
                        input_schema_version=1, output_schema_version=1,
                        prompt_version="current-version", content_hash=hashlib.sha256(body).hexdigest(),
                        activation_status="ACTIVE", node_dev_pass=True, node_holdout_pass=True,
                        safety_gate_pass=True, manifest_approved=True)
            slots.append(slot)
            entries.append({k: slot[k] for k in ("prompt_slot_id", "runtime_node_id", "input_schema_version", "output_schema_version")})
        if mismatch:
            entries[-1]["output_schema_version"] = 999
        if missing:
            slots[-1].pop("runtime_node_id")
            entries[-1].pop("runtime_node_id")
        manifest = dict(prompt_bundle_version=data["base_prompt_bundle_version"], slots=slots)
        (self.root / data["base_prompt_manifest"]).write_text(json.dumps(manifest), encoding="utf-8")
        (self.root / data["base_input_contract"]).write_text(json.dumps(dict(entries=entries)), encoding="utf-8")
        return directory

    def _run(self, **kwargs):
        from prompt_candidate import materialize_prompt_candidate
        return materialize_prompt_candidate(candidate_path=self.candidate, repository_root=self.root,
                                            output_dir=self.root / "output", **kwargs)

    def test_non_21_candidate_count_uses_manifest_identity_not_magic_number(self) -> None:
        from prompt_candidate import load_prompt_candidate
        data = self._data()
        keep = dict(list(data["sources"].items())[:2])
        for slot, entry in data["sources"].items():
            if slot not in keep:
                (self.candidate / entry["source"]).unlink()
        data["sources"] = keep
        data["prompt_slot_count"] = len(keep)
        self._save(data)
        self.assertEqual(len(keep), len(load_prompt_candidate(self.candidate, repository_root=self.root).source_hashes))

    def test_zero_slot_candidate_rejected(self) -> None:
        from prompt_candidate import PromptCandidateError, load_prompt_candidate
        data = self._data()
        data["prompt_slot_count"] = 0
        self._save(data)
        with self.assertRaises(PromptCandidateError):
            load_prompt_candidate(self.candidate, repository_root=self.root)

    def test_count_mismatch_rejected(self) -> None:
        from prompt_candidate import PromptCandidateError, load_prompt_candidate
        data = self._data()
        data["prompt_slot_count"] += 1
        self._save(data)
        with self.assertRaises(PromptCandidateError):
            load_prompt_candidate(self.candidate, repository_root=self.root)

    def test_same_set_materializes_a_draft_without_source_mutation(self) -> None:
        import json
        base = self._base()
        original = {p: p.read_bytes() for p in base.rglob("*") if p.is_file()}
        result = self._run()
        out = json.loads(result.prompt_manifest_path.read_text())
        self.assertEqual(set(self._data()["sources"]), {s["prompt_slot_id"] for s in out["slots"]})
        for slot in out["slots"]:
            self.assertEqual("DRAFT", slot["activation_status"])
            self.assertIs(False, slot["node_dev_pass"])
            self.assertEqual((self.candidate / slot["source"]).read_bytes(), (result.output_dir / slot["source"]).read_bytes())
        self.assertEqual(original, {p: p.read_bytes() for p in base.rglob("*") if p.is_file()})

    def test_extra_product_slot_rejected_without_explicit_option(self) -> None:
        from prompt_candidate import PromptCandidateError
        self._base(extra=True)
        with self.assertRaisesRegex(PromptCandidateError, "Product-only"):
            self._run()
        self.assertFalse((self.root / "output").exists())

    def test_extra_product_slot_kept_byte_for_byte_with_opt_in(self) -> None:
        import json
        base = self._base(extra=True)
        result = self._run(keep_extra_product_slots=True)
        name = "request_understanding.identify_temporal_scope"
        self.assertEqual((base / f"sources/{name}.md").read_bytes(), (result.output_dir / f"sources/{name}.md").read_bytes())
        slots = json.loads(result.prompt_manifest_path.read_text())["slots"]
        self.assertEqual(len(self._data()["sources"]) + 1, len(slots))
        extra = next(s for s in slots if s["prompt_slot_id"] == name)
        self.assertEqual("current-version", extra["prompt_version"])
        self.assertEqual("DRAFT", extra["activation_status"])

    def test_missing_extra_source_is_not_invented(self) -> None:
        from prompt_candidate import PromptCandidateError
        base = self._base(extra=True)
        (base / "sources/request_understanding.identify_temporal_scope.md").unlink()
        with self.assertRaises(PromptCandidateError):
            self._run(keep_extra_product_slots=True)
        self.assertFalse((self.root / "output").exists())

    def test_extra_source_hash_tampering_rejected(self) -> None:
        from prompt_candidate import PromptCandidateError
        base = self._base(extra=True)
        (base / "sources/request_understanding.identify_temporal_scope.md").write_text("changed")
        with self.assertRaisesRegex(PromptCandidateError, "source hash mismatch"):
            self._run(keep_extra_product_slots=True)
        self.assertFalse((self.root / "output").exists())

    def test_schema_mismatch_leaves_no_partial_output(self) -> None:
        from prompt_candidate import PromptCandidateError
        self._base(mismatch=True)
        with self.assertRaisesRegex(PromptCandidateError, "contract mismatch"):
            self._run()
        self.assertFalse((self.root / "output").exists())

    def test_missing_metadata_does_not_pass_as_none_equals_none(self) -> None:
        from prompt_candidate import PromptCandidateError
        self._base(missing=True)
        with self.assertRaisesRegex(PromptCandidateError, "missing current"):
            self._run()
        self.assertFalse((self.root / "output").exists())

    def test_manifest_contract_different_sets_rejected_even_with_opt_in(self) -> None:
        import json
        from prompt_candidate import PromptCandidateError
        self._base(extra=True)
        contract = self.root / self._data()["base_input_contract"]
        data = json.loads(contract.read_text())
        data["entries"].pop()
        contract.write_text(json.dumps(data))
        with self.assertRaisesRegex(PromptCandidateError, "slot sets differ"):
            self._run(keep_extra_product_slots=True)

    def test_empty_output_directory_is_supported(self) -> None:
        self._base()
        (self.root / "output").mkdir()
        self.assertTrue(self._run().prompt_manifest_path.is_file())

    def test_existing_output_file_is_preserved(self) -> None:
        from prompt_candidate import PromptCandidateError
        self._base()
        path = self.root / "output"
        path.write_text("keep me")
        with self.assertRaises(PromptCandidateError):
            self._run()
        self.assertEqual("keep me", path.read_text())

    def test_second_materialization_does_not_overwrite(self) -> None:
        from prompt_candidate import PromptCandidateError
        self._base()
        first = self._run()
        before = first.prompt_manifest_path.read_bytes()
        with self.assertRaises(PromptCandidateError):
            self._run()
        self.assertEqual(before, first.prompt_manifest_path.read_bytes())

    def test_product_source_output_is_rejected(self) -> None:
        from prompt_candidate import PromptCandidateError, materialize_prompt_candidate
        base = self._base()
        with self.assertRaises(PromptCandidateError):
            materialize_prompt_candidate(candidate_path=self.candidate, repository_root=self.root, output_dir=base / "other")

    def test_slot_filename_alias_rejected(self) -> None:
        from prompt_candidate import PromptCandidateError, load_prompt_candidate
        data = self._data()
        first, second = list(data["sources"])[:2]
        data["sources"][first] = dict(data["sources"][second])
        self._save(data)
        with self.assertRaisesRegex(PromptCandidateError, "slot filename"):
            load_prompt_candidate(self.candidate, repository_root=self.root)

    def test_duplicate_json_key_rejected(self) -> None:
        from prompt_candidate import PromptCandidateError, load_prompt_candidate
        (self.candidate / "candidate.json").write_text('{"schema_version":1,"schema_version":1}')
        with self.assertRaisesRegex(PromptCandidateError, "duplicate JSON key"):
            load_prompt_candidate(self.candidate, repository_root=self.root)

    def test_unregistered_source_file_rejected(self) -> None:
        from prompt_candidate import PromptCandidateError, load_prompt_candidate
        (self.candidate / "sources/unregistered.md").write_text("unregistered")
        with self.assertRaisesRegex(PromptCandidateError, "source-file sets differ"):
            load_prompt_candidate(self.candidate, repository_root=self.root)

    def test_manifest_input_contract_bytes_are_preserved(self) -> None:
        self._base(extra=True)
        original = (self.root / self._data()["base_input_contract"]).read_bytes()
        self.assertEqual(original, self._run(keep_extra_product_slots=True).input_contract_path.read_bytes())


class ReadableGoldBoundaryTests(unittest.TestCase):
    """Check evaluator-only placement, not LLM answer correctness."""

    def test_bilingual_variants_have_both_languages_per_question(self) -> None:
        import re
        root = Path(__file__).resolve().parents[1]
        groups = []
        for path in (root / "datasets").glob("*.md"):
            for block in re.split(r"(?=^### 질문 )", path.read_text(encoding="utf-8"), flags=re.M)[1:]:
                if "**같은 뜻의 다른 말투**" in block:
                    groups.append(block)
                    self.assertIn("한국어:\n>", block)
                    self.assertIn("English:\n>", block)
                    before = block.split("**평가자 확인")[0]
                    self.assertEqual(3, len(re.findall(r"^> ", before, re.M)))
        self.assertTrue(groups)

    def test_gold_and_user_questions_do_not_enter_upload_materials(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for path in (root / "datasets").glob("*.md"):
            material = extract_materials(path.read_text(encoding="utf-8"))
            outside = "\n".join(line for _, line in outside_fence_lines(material))
            self.assertNotIn("**평가자 확인", outside)
            self.assertNotIn("**같은 뜻의 다른 말투**", outside)


class EmailScopeTests(unittest.TestCase):
    """Evaluation text restrictions only; never a production authorization test."""

    def test_exactly_three_user_supplied_accounts_are_allowed(self) -> None:
        self.assertEqual({
            "jjssyy0527@gmail.com", "bonggyulim0728@gmail.com", "qhdrbdhkdwks2@gmail.com",
        }, set(ALLOWED_EMAIL_ADDRESSES))
        validate_material_emails("From/To/CC/BCC: " + ", ".join(ALLOWED_EMAIL_ADDRESSES))

    def test_case_is_supported_without_alias_normalization(self) -> None:
        validate_material_emails("JJSSYY0527@GMAIL.COM")

    def test_unlisted_account_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unapproved email"):
            validate_material_emails("other" + "@" + "invalid.test")

    def test_plus_and_dot_aliases_are_not_extra_allowed_accounts(self) -> None:
        for local in ("jjssyy0527+case", "jj.ss.yy0527"):
            with self.subTest(local=local), self.assertRaises(ValueError):
                validate_material_emails(local + "@" + "gmail.com")

    def test_allowed_email_prefix_does_not_allow_other_domain(self) -> None:
        with self.assertRaises(ValueError):
            validate_material_emails("jjssyy0527@gmail.com" + ".invalid")

    def test_raw_business_payload_is_checked(self) -> None:
        invalid = "other" + "@" + "invalid.test"
        with self.assertRaises(ValueError):
            extract_materials(SAMPLE.replace("등록할 업무 내용", "연락처: " + invalid))

    def test_question_and_gold_are_checked_even_though_not_exported(self) -> None:
        invalid = "other" + "@" + "invalid.test"
        for old in ("시험 질문", "평가자 정답은 외부에 올리지 않음"):
            with self.subTest(old=old), self.assertRaises(ValueError):
                extract_materials(SAMPLE.replace(old, invalid))

    def test_linked_text_attachment_with_other_email_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scenario = make_workspace(root)
            attachment = root / "datasets" / "attachment.txt"
            attachment.write_text("other" + "@" + "invalid.test", encoding="utf-8")
            scenario.write_text(SAMPLE.replace("제목: 업무 메일", "첨부: [자료](attachment.txt)"), encoding="utf-8")
            with self.assertRaises(ValueError):
                read_scenario(scenario, root)

    def test_workspace_checks_nested_attachments_and_safety_examples(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_workspace(root)
            assets = root / "datasets" / "attachments"
            assets.mkdir()
            (assets / "payload.csv").write_text("recipient\n" + "other" + "@" + "invalid.test", encoding="utf-8")
            checks = root / "checks"
            checks.mkdir()
            (checks / "safety.md").write_text("# Safety\n" + "unrequested" + "@" + "invalid.test", encoding="utf-8")
            failures = check_workspace(root)
            self.assertTrue(any("payload.csv" in error and "Unapproved email" in error for error in failures))
            self.assertTrue(any("safety.md" in error and "Unapproved email" in error for error in failures))

    def test_rejected_address_does_not_create_export_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scenario = make_workspace(root)
            scenario.write_text(SAMPLE.replace("등록할 업무 내용", "other" + "@" + "invalid.test"), encoding="utf-8")
            output = root / "export.md"
            with self.assertRaises(ValueError):
                export_to_file(scenario, output, root)
            self.assertFalse(output.exists())

    def test_current_text_data_contains_only_the_three_accounts(self) -> None:
        root = Path(__file__).resolve().parents[1]
        seen = set()
        for folder in (root / "datasets", root / "checks"):
            for path in folder.rglob("*"):
                if path.is_file() and path.suffix in (".md", ".txt", ".csv"):
                    text = path.read_text(encoding="utf-8-sig")
                    validate_material_emails(text)
                    seen.update(m.group().casefold() for m in EMAIL_ADDRESS.finditer(text))
        self.assertEqual(set(ALLOWED_EMAIL_ADDRESSES), seen)

    def test_same_name_senders_stay_distinct(self) -> None:
        import re
        root = Path(__file__).resolve().parents[1]
        text = extract_materials((root / "datasets" / "aster-nova-동명이인.md").read_text(encoding="utf-8"))
        senders = re.findall(r"발신 박민수 <([^>]+)>", text)
        self.assertEqual(["jjssyy0527@gmail.com", "qhdrbdhkdwks2@gmail.com"], senders)

    def test_grove_new_recipient_is_not_in_original_thread(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = (root / "datasets" / "grove-캠페인.md").read_text(encoding="utf-8")
        material = extract_materials(text)
        self.assertIn("jjssyy0527@gmail.com", material)
        self.assertIn("bonggyulim0728@gmail.com", material)
        self.assertNotIn("qhdrbdhkdwks2@gmail.com", material)
        self.assertIn("qhdrbdhkdwks2@gmail.com", text.split("## 시험 질문과 확인 기준", 1)[1])

    def test_aurora_two_kims_and_forward_recipient_not_merged(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = extract_materials((root / "datasets" / "오로라-현장과연수.md").read_text(encoding="utf-8"))
        self.assertIn("발신 김하늘 대리 <jjssyy0527@gmail.com>", text)
        self.assertIn("발신 김바다 대리 <qhdrbdhkdwks2@gmail.com>", text)
        forward = text.split("### 메일 대화 4 — 오로라 참고 전달", 1)[1].split("### 메일 대화 5", 1)[0]
        self.assertIn("발신: 업무 취합 담당 <bonggyulim0728@gmail.com>", forward)
        self.assertIn("수신: jjssyy0527@gmail.com", forward)
        self.assertIn("참조: bonggyulim0728@gmail.com", forward)


if __name__ == "__main__":
    unittest.main()
