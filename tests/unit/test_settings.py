"""Each service reads its environment once through a pydantic Settings model: typed, validated, named."""

from datetime import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from gateway.settings import GatewaySettings
from main.settings import MainSettings
from memory.settings import MemorySettings
from supervisor.settings import SupervisorSettings
from telegram_bridge import TelegramSettings
from tracer import TracerSettings

PG = "postgresql://mycelium:pw@postgres:5432/mycelium"


def test_memory_defaults_overrides_and_errors_name_the_variable():
    s = MemorySettings.model_validate({"DATABASE_URL": PG})
    assert s.database_url == PG and s.schema_name == "memory" and s.vault_dir == Path("/vault")
    assert s.tz == "Asia/Taipei" and s.consolidate_at == time(3, 30)
    assert s.nats_url == "nats://nats:4222" and s.log_level == "INFO"

    s = MemorySettings.model_validate(
        {
            "MEMORY_DATABASE_URL": "postgresql://m@db/memory",  # memory's own database wins when set
            "DATABASE_URL": PG,
            "MEMORY_CONSOLIDATE_AT": "",  # empty: the nightly job is off
            "MEMORY_TZ": "Europe/Berlin",
            "MEMORY_VAULT_DIR": "/data/vault",
        }
    )
    assert s.database_url == "postgresql://m@db/memory" and s.consolidate_at is None
    assert s.tz == "Europe/Berlin" and s.vault_dir == Path("/data/vault")

    with pytest.raises(ValidationError, match="DATABASE_URL"):
        MemorySettings.model_validate({})
    with pytest.raises(ValidationError, match="MEMORY_TZ"):
        MemorySettings.model_validate({"DATABASE_URL": PG, "MEMORY_TZ": "Mars/Olympus"})
    with pytest.raises(ValidationError, match="MEMORY_SCHEMA"):
        MemorySettings.model_validate({"DATABASE_URL": PG, "MEMORY_SCHEMA": "Bad-Name"})
    with pytest.raises(ValidationError, match="MEMORY_CONSOLIDATE_AT"):
        MemorySettings.model_validate({"DATABASE_URL": PG, "MEMORY_CONSOLIDATE_AT": "half past three"})


def test_settings_come_from_the_environment(monkeypatch):
    for name in ("MEMORY_DATABASE_URL", "DATABASE_URL", "MEMORY_CONSOLIDATE_AT", "MEMORY_TZ", "NATS_URL", "LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_URL", PG)
    monkeypatch.setenv("MEMORY_CONSOLIDATE_AT", "04:15")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("NATS_URL", "nats://localhost:4222")
    s = MemorySettings()
    assert s.database_url == PG and s.consolidate_at == time(4, 15)
    assert s.log_level == "DEBUG" and s.nats_url == "nats://localhost:4222"


def test_gateway_main_telegram_and_tracer_settings():
    assert GatewaySettings.model_validate({}).config == Path("/srv/gateway/providers.yaml")
    with pytest.raises(ValidationError, match="LOG_LEVEL"):
        GatewaySettings.model_validate({"LOG_LEVEL": "loud"})

    m = MainSettings.model_validate({"MAIN_LLM_TIMEOUT": "120"})
    assert m.llm_timeout == 120.0 and m.max_turns == 20 and m.tz == "Asia/Taipei"
    with pytest.raises(ValidationError, match="MAIN_MAX_TURNS"):
        MainSettings.model_validate({"MAIN_MAX_TURNS": 0})

    t = TelegramSettings.model_validate({"TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_CHAT_ID": "4242"})
    assert t.chat_id == 4242 and t.bot_token == "123:abc"
    with pytest.raises(ValidationError, match="TELEGRAM_BOT_TOKEN"):  # compose passes "" when .env has no token
        TelegramSettings.model_validate({"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": 1})

    tr = TracerSettings.model_validate({"DATABASE_URL": PG})
    assert tr.event_retention_days == 365
    with pytest.raises(ValidationError, match="EVENT_RETENTION_DAYS"):
        TracerSettings.model_validate({"DATABASE_URL": PG, "EVENT_RETENTION_DAYS": "0"})


def test_supervisor_settings_derive_networks_from_the_stack():
    s = SupervisorSettings.model_validate(
        {
            "DATABASE_URL": PG,
            "STACK": "mycelium-dev",
            "APPROVED_ACTUATORS": "lights, expenses,",
            "RECONCILE_ON_START": "false",
        }
    )
    assert s.module_network == "mycelium-dev-modules" and s.internet_network == "mycelium-dev-mesh"
    assert s.approved == {"lights", "expenses"} and s.reconcile_on_start is False
    assert s.modules_dir == Path("/workspace/modules") and s.sdk_dir == Path("/workspace/sdk")
    custom = SupervisorSettings.model_validate({"DATABASE_URL": PG, "MODULE_NETWORK": "shared-bus"})
    assert custom.module_network == "shared-bus" and custom.internet_network == "mycelium-mesh"
    assert SupervisorSettings.model_validate({"DATABASE_URL": PG}).approved == set()
    with pytest.raises(ValidationError, match="STACK"):
        SupervisorSettings.model_validate({"DATABASE_URL": PG, "STACK": "Prod Stack"})
    assert s.grown_dir is None and s.module_tz == "UTC" and s.verify_timeout == 300
    grown = SupervisorSettings.model_validate(
        {"DATABASE_URL": PG, "GROWN_DIR": "/workspace/grown", "MODULE_TZ": "Asia/Taipei", "VERIFY_TIMEOUT": "120"}
    )
    assert grown.grown_dir == Path("/workspace/grown") and grown.module_tz == "Asia/Taipei"
    assert grown.verify_timeout == 120
    with pytest.raises(ValidationError, match="unknown timezone"):
        SupervisorSettings.model_validate({"DATABASE_URL": PG, "MODULE_TZ": "Mars/Olympus"})


def test_memory_today_is_the_local_date_not_the_containers_utc_clock():
    from datetime import UTC, date, datetime

    s = MemorySettings.model_validate({"DATABASE_URL": PG, "MEMORY_TZ": "Pacific/Kiritimati"})  # UTC+14
    local = s.today()
    assert isinstance(local, date) and local >= datetime.now(UTC).date()
