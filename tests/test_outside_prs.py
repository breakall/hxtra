""".github/workflows/outside-prs.yml retargets outside pull requests from main to next; it runs
on pull_request_target with a write token, so it must never check out or run the PR's code."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = (ROOT / ".github/workflows/outside-prs.yml").read_text()


def test_runs_from_the_base_branch():
    assert "pull_request_target:" in WORKFLOW
    assert "base.ref == 'main'" in WORKFLOW
    assert "base=next" in WORKFLOW


def test_never_touches_pr_code():
    for word in ("actions/checkout", "head.sha", "head.ref", "git ", "github.event.pull_request.title",
                 "github.event.pull_request.body"):
        assert word not in WORKFLOW


def test_collaborators_keep_their_base():
    for role in ("OWNER", "MEMBER", "COLLABORATOR"):
        assert f'"{role}"' in WORKFLOW
