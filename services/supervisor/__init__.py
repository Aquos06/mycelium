"""The supervisor (ARCHITECTURE §3): the only service with Docker. Everyone else asks it over the bus.

__main__.py     entrypoint: `python -m supervisor`
settings.py     MODULES_DIR, GROWN_DIR, MODULE_TZ, VERIFY_TIMEOUT, the networks, the stack name, APPROVED_ACTUATORS
service.py      Supervisor: rpc.sys.* handlers (deploy, verify, stop, logs, list, health) and reconcile
docker_ops.py   DockerOps: build, run, stop, logs, and the locked-down test run behind verify
registry.py     which modules should be running (Postgres; in memory for tests)
schemas.py      VerifyResult, what rpc.sys.verify answers
"""
