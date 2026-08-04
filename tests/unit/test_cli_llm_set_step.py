"""CLI tests for `amber llm set-step` registry validation (see issue #98)."""

from contextlib import asynccontextmanager

from typer.testing import CliRunner

from src.cli.commands.llm import app

runner = CliRunner()


def _out(result) -> str:
    """Collapse whitespace/line-wraps in rich's terminal output so an
    assertion doesn't depend on where a non-tty width happens to wrap a
    long message."""
    return " ".join(result.output.split())


class _FakeTenant:
    def __init__(self):
        self.id = "default"
        self.config: dict = {}


class _FakeResult:
    def __init__(self, tenant):
        self._tenant = tenant

    def scalar_one_or_none(self):
        return self._tenant


class _FakeSession:
    def __init__(self, tenant):
        self._tenant = tenant

    async def execute(self, *_args, **_kwargs):
        return _FakeResult(self._tenant)

    async def commit(self):
        pass


def _patch_session(monkeypatch, tenant: _FakeTenant) -> None:
    @asynccontextmanager
    async def _fake_session_scope():
        yield _FakeSession(tenant)

    monkeypatch.setattr("src.cli.commands.llm.session_scope", _fake_session_scope)


def test_set_step_rejects_unknown_model_without_force(monkeypatch):
    tenant = _FakeTenant()
    _patch_session(monkeypatch, tenant)

    result = runner.invoke(
        app,
        ["set-step", "chat.generation", "--provider", "openai", "--model", "gpt-retired-999"],
    )

    assert result.exit_code != 0
    assert "gpt-retired-999" in _out(result)
    assert "--force" in _out(result)
    assert tenant.config == {}


def test_set_step_accepts_unknown_model_with_force_and_warns(monkeypatch):
    tenant = _FakeTenant()
    _patch_session(monkeypatch, tenant)

    result = runner.invoke(
        app,
        [
            "set-step",
            "chat.generation",
            "--provider",
            "openai",
            "--model",
            "gpt-retired-999",
            "--force",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Warning" in _out(result)
    assert "gpt-retired-999" in _out(result)
    assert tenant.config["llm_steps"]["chat.generation"]["model"] == "gpt-retired-999"


def test_set_step_accepts_known_model_without_force(monkeypatch):
    tenant = _FakeTenant()
    _patch_session(monkeypatch, tenant)

    result = runner.invoke(
        app,
        ["set-step", "chat.generation", "--provider", "openai", "--model", "gpt-4o-mini"],
    )

    assert result.exit_code == 0, result.output
    assert tenant.config["llm_steps"]["chat.generation"]["model"] == "gpt-4o-mini"


def test_set_step_validates_merged_result_not_raw_delta(monkeypatch):
    """Regression test for issue #98 (B2): a --model-only delta merged onto
    an already-stored --provider must be validated as the PAIR that will
    actually be persisted, not validated in isolation. 'llama3' is a real,
    known model -- but only under provider 'ollama', never 'openai' -- so
    validating the --model delta alone (which passes: SOME provider knows
    it) would miss that it's wrong for the 'openai' provider already
    stored on this step."""
    tenant = _FakeTenant()
    tenant.config = {"llm_steps": {"chat.generation": {"provider": "openai"}}}
    _patch_session(monkeypatch, tenant)

    result = runner.invoke(
        app,
        ["set-step", "chat.generation", "--model", "llama3"],
    )

    assert result.exit_code != 0
    assert "llama3" in _out(result)
    assert "openai" in _out(result)
    # The pre-existing provider must be untouched by the rejected write.
    assert tenant.config["llm_steps"]["chat.generation"] == {"provider": "openai"}


def test_set_step_model_only_override_resolved_against_any_known_provider(monkeypatch):
    """A --model-only override on a step with no provider stored yet is
    valid as long as SOME provider in the registry knows the model."""
    tenant = _FakeTenant()
    _patch_session(monkeypatch, tenant)

    result = runner.invoke(
        app,
        ["set-step", "chat.generation", "--model", "gpt-4o-mini"],
    )

    assert result.exit_code == 0, result.output
    assert tenant.config["llm_steps"]["chat.generation"]["model"] == "gpt-4o-mini"
