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

## Status of Laya (2026-10-24, first live run)

The server works: a decision with three typed questions answers in ~300 ms over the LAN, with
per-option probabilities, routing and token usage. The **base checkpoint is not usable for our
questions yet**: on eight obvious "which kind of memory does this need" cases it picked `none` six to
eight times, with sharper criteria wording making it worse; only the yes/no "is this a durable fact"
question carried signal. The model card says as much: base checkpoints are near chance until fine-tuned.

Plan: the gateway's `decide` slot runs a forced tool call on the chat model as `active` and Laya as
`shadow`; every decision and the planner's actual behaviour land in the traces, which becomes the
labelled set to fine-tune Laya on (the card shows fine-tuning on two free T4s). Then flip `active`.

Latency to check: ~300 ms matches the card's CPU numbers, not its 33 ms on a GPU. Inside the container:
`docker compose exec laya python -c "import torch; print(torch.cuda.is_available())"`.
