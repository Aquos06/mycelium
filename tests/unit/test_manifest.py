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


@pytest.mark.parametrize(
    "sub", [">", "*", "rpc.sys.deploy", "_INBOX.abc", "bad subject", "trace.plan", "stream.llm", "*.chat"]
)
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


@pytest.mark.parametrize("name", ["expenses\n", "expenses\nx"])
def test_a_name_with_a_newline_is_refused(name):
    with pytest.raises(ManifestError):
        validate_manifest({"name": name, "purpose": "Tracks what Hansen spends in chat."})


# ---- described requests (docs/ARCHITECTURE.md §4) ----------------------------------------------------

DESCRIBED = {
    "add": {
        "description": "Store one expense.",
        "params": {"amount": "number", "description": "string", "day?": "date"},  # block-style `day?:` is taken
        "returns": {"id": "number"},
    },
    "summary": "Totals for a date range, all time by default.",
    "history": None,
}


def test_described_requests_keep_the_names_and_their_specs():
    man = validate_manifest(m(requests=DESCRIBED))
    assert man.requests == ["add", "summary", "history"]  # every reader of the names keeps working
    assert man.request_specs["add"].signature() == "{amount: number, description: string, day: optional date}"
    assert man.request_specs["summary"].params == {}
    assert man.undescribed() == ["history"]


def test_a_dumped_manifest_validates_again_unchanged():
    """The supervisor stores model_dump() and serves it; reading that back must give the same manifest."""
    man = validate_manifest(m(requests=DESCRIBED))
    assert validate_manifest(man.model_dump()) == man


def test_named_requests_still_validate_and_are_undescribed():
    man = validate_manifest(m(requests=["summary"]))
    assert man.request_specs == {} and man.undescribed() == ["summary"]


@pytest.mark.parametrize(
    "spec",
    [
        {"description": "short"},  # a real description
        {"description": "Store one expense.", "params": {"Amount": "number"}},  # lowercase names
        {"description": "Store one expense.", "params": {"amount": ""}},  # a type
    ],
)
def test_bad_request_specs(spec):
    with pytest.raises(ManifestError):
        validate_manifest(m(requests={"add": spec}))


def test_a_spec_must_describe_a_declared_request():
    with pytest.raises(ManifestError, match="not in `requests`"):
        validate_manifest(m(requests=["add"], request_specs={"remove": {"description": "Remove one entry."}}))
