import pytest

from mycelium_sdk import ManifestError, load_manifest, validate_manifest

BASE = {"name": "expenses", "purpose": "Tracks spending mentioned in chat."}


def m(**over):
    return {**BASE, **over}


def test_minimal_valid():
    man = validate_manifest(m())
    assert man.event_subject("x.y") == "mod.expenses.x.y"
    assert man.rpc_subject("summary") == "rpc.mod.expenses.summary"
    assert man.permissions.network is False and man.permissions.actuation is False


@pytest.mark.parametrize("name", ["Expenses", "e", "1abc", "has_underscore", "a" * 40, "sys", "brain", "rpc"])
def test_bad_names(name):
    with pytest.raises(ManifestError):
        validate_manifest(m(name=name))


def test_purpose_required():
    with pytest.raises(ManifestError):
        validate_manifest({"name": "expenses", "purpose": "x"})


@pytest.mark.parametrize("sub", [">", "*", "rpc.sys.deploy", "_INBOX.abc", "bad subject"])
def test_forbidden_subscriptions(sub):
    with pytest.raises(ManifestError):
        validate_manifest(m(subscribes=[sub]))


def test_self_loop_rejected():
    with pytest.raises(ManifestError, match="loop"):
        validate_manifest(m(subscribes=["mod.expenses.logged"]))


@pytest.mark.parametrize("field", ["emits", "requests"])
def test_emits_and_requests_must_be_concrete(field):
    with pytest.raises(ManifestError):
        validate_manifest(m(**{field: ["mod.*"]}))


def test_interval_floor():
    with pytest.raises(ManifestError):
        validate_manifest(m(hooks={"interval_seconds": [5]}))


def test_resource_bounds():
    with pytest.raises(ManifestError):
        validate_manifest(m(resources={"memory_mb": 100000}))


def test_load_manifest_errors(tmp_path):
    with pytest.raises(ManifestError, match="not found"):
        load_manifest(tmp_path / "nope.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: [unclosed")
    with pytest.raises(ManifestError, match="YAML"):
        load_manifest(bad)
    lst = tmp_path / "list.yaml"
    lst.write_text("- a\n- b\n")
    with pytest.raises(ManifestError, match="mapping"):
        load_manifest(lst)
