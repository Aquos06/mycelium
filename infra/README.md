# infra/

Things that run on the GPU workstation next to the stack, each a compose file of its own: clone the repo
there, `cd infra/<thing>`, `cp .env.example .env`, `docker compose up -d`, then point the stack at it from
`.env`.

| dir | what | the stack's side |
|---|---|---|
| `embed/` | Text Embeddings Inference: `BAAI/bge-m3` on port 8101 (memory's vectors) and `BAAI/bge-reranker-v2-m3` on 8102 (the decide step's scorer) | `EMBED_PROVIDER=tei`, `TEI_ENDPOINT=http://<box>:8101/v1`, `DECIDE_PROVIDER=tei`, `TEI_RERANK_ENDPOINT=http://<box>:8102` |

`scripts/bench_decide.py` compares the scorers; the numbers are in docs/MEMORY.md (The decide step).

vLLM for the planner and consolidation is run by hand on the box today (`VLLM_ENDPOINT`, `VLLM_MODEL`);
the main compose also carries `vllm` and `tei` under the `gpu` profile for a stack that lives on the box itself.
