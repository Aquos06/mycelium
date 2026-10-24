# infra: what runs on the GPU workstation

The brain (bus, Main, memory, gateway, supervisor) runs from the root `docker-compose.yml`. The muscle,
the model servers, runs here, on the box with the GPUs, and the gateway reaches it over the LAN like
any other provider. Nothing in this folder knows about mycelium: no bus, no settings model, no tables.
Each subfolder is one pinned container around open software, started on its own.

| folder | what | port on the box | gateway kind |
|---|---|---|---|
| `laya/` | Laya, the local decision model (choice / score / yes-no with probabilities) behind `laya-serve` | 8100 | `laya` (the `gate` and `decide` slots) |
| vLLM | the planner's local model; today started by hand, moves here next | 8000 | `vllm` |

## On the workstation

```sh
git clone <this repo> && cd mycelium/infra/laya
cp .env.example .env                 # LAYA_DEVICE=cuda is the default
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
python3 smoke.py http://localhost:8100   # one decision, three question types
```

Without an NVIDIA GPU (a laptop, CI), leave the override out and set `LAYA_DEVICE=cpu`; answers take a
few hundred milliseconds instead of tens.

## On the Mac that runs the brain

Point the gateway at the box in the root `.env`:

```
LAYA_ENDPOINT=http://192.168.0.107:8100
```

and set `gate` / `decide` to `laya` in `services/gateway/providers.yaml`.
