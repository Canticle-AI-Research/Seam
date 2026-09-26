"""Tests for SEAM Skill Factory foundation."""

from __future__ import annotations

import unittest

import yaml  # type: ignore  # noqa: F401

from seam_runtime.skills import (
    SkillIR,
    SkillObservation,
    identify_agent,
    propose_skill_from_observation,
)
from tools.skills.compiler import SUPPORTED_TARGETS, compile_skill_for_targets, render_skill


class TestAgentIdentity(unittest.TestCase):
    def test_explicit_agent_override_wins(self):
        ident = identify_agent({"SEAM_AGENT": "codex"}, {})
        self.assertEqual(ident.agent, "codex")
        self.assertEqual(ident.confidence, 1.0)
        self.assertIn("codex.yaml", ident.profile)

    def test_repo_file_fallback(self):
        ident = identify_agent({}, {"AGENTS.md": True})
        self.assertEqual(ident.agent, "codex")
        self.assertGreaterEqual(ident.confidence, 0.7)

    def test_unknown_falls_back_to_generic(self):
        ident = identify_agent({}, {})
        self.assertEqual(ident.agent, "generic")
        self.assertLess(ident.confidence, 0.5)


class TestSkillObservation(unittest.TestCase):
    def test_observation_to_proposal(self):
        obs = SkillObservation.from_dict(
            {
                "observation_id": "obs_docs_index_001",
                "agent": "codex",
                "task": "documentation update",
                "issue": "Agent added docs but missed the docs index.",
                "automatable": True,
                "suggested_skill": "docs-index-sync",
                "evidence": ["new docs file", "docs/README.md unchanged"],
                "proposed_rule": "When adding docs, check the docs index.",
                "repeat_count": 3,
            }
        )
        proposal = propose_skill_from_observation(obs)
        self.assertEqual(proposal.skill, "docs-index-sync")
        self.assertEqual(proposal.agent, "codex")
        self.assertIn("obs_docs_index_001", proposal.source_observations)
        self.assertIn("docs index", proposal.proposed_rules[0])


class TestSkillRendering(unittest.TestCase):
    def _ir(self) -> SkillIR:
        return SkillIR.from_dict(
            {
                "schema_version": "1.0",
                "name": "demo",
                "title": "Demo Skill",
                "description": "Demo description",
                "short_description": "Demo",
                "purpose": "Prove rendering works.",
                "safety_rules": ["Do not silently rewrite installed skills."],
                "workflow": [
                    {"number": 1, "title": "Inspect", "body": "Inspect state."}
                ],
                "output_format": "Done: <state>",
            }
        )

    def test_render_all_targets(self):
        ir = self._ir()
        for target in SUPPORTED_TARGETS:
            out = render_skill(ir, target, "0" * 64)
            self.assertIn("Demo Skill", out)
            self.assertIn("source_spec_sha256", out)
            self.assertIn("Do not silently rewrite", out)

    def test_compile_all_targets_paths(self):
        compiled = compile_skill_for_targets("skills/source/session-end.yaml", ["all"])
        self.assertEqual({item.target for item in compiled}, set(SUPPORTED_TARGETS))
        for item in compiled:
            self.assertTrue(item.output_path.startswith("skills/generated/"))
            self.assertIn(item.skill, item.output_path)


if __name__ == "__main__":
    unittest.main()
