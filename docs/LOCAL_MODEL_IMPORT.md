# Local Model Import

ModelForge can register an already-downloaded local model without copying, moving, modifying, deleting, downloading, or installing anything. The import path is:

1. `POST /api/v1/models/local/detect` with `{"path":"/path/to/model"}`.
2. Review the returned `format`, `architecture`, `capabilities`, `evidence`, `missing_files`, `uncertain`, `runtime_options`, and `unavailable_reasons`.
3. `POST /api/v1/models/local/register` with the same path, optional corrected `capabilities`, optional `preferred_runtime`, and `load: true` only when the user wants runtime loading immediately.
4. Use `GET /api/v1/models/{model_id}/operations` or `/v1/models/{model}` to inspect available operations and request examples.

## Safety Model

Downloaded/scanned models under the configured model root still use the existing contained-path validation. External paths selected by the desktop client are only loadable after explicit registration through the local import endpoint. Registration stores the resolved real path in `data/local_model_paths.json` and in the model record metadata. Runtime resolution requires both records to match, so symlink targets and moved files are rechecked before use.

Removing a model record never deletes the original file. Loaded runtime state is process-local; after restart, a persisted `loaded` status is displayed as `ready` unless the runtime manager has an active instance.

The detector is offline-only. It reads local config/header files and does not download missing shards, install dependencies, or enable `trust_remote_code`.

## Supported Matrix

| Format / structure | Detected capabilities | Runtime status |
| --- | --- | --- |
| GGUF/GGML file or directory containing GGUF | `CHAT`, `INFERENCE` | `llama_cpp` when `llama-cpp-python` is installed |
| Hugging Face causal LM directory with `config.json` and complete weights | `CHAT`, `INFERENCE`, `TRAINING` | `transformers` when `transformers` and `torch` are installed |
| Sentence-transformers / encoder directory | `EMBEDDING` | `transformers_embedding` when `transformers` and `torch` are installed |
| PEFT LoRA/Adapter | `LORA` | Not independently loadable; requires a compatible base model and adapter mounting is not implemented |
| Diffusers `model_index.json` Wan T2V pipeline | `VIDEO` | `wan-diffusers` when local files, Python dependencies, and Apple MPS/BF16 probe pass |
| Other known Diffusers image pipelines | `IMAGE` | Registered only; generic image runtime is not connected in this build |
| Unknown Diffusers pipelines | none until manually reviewed | Not loadable; unknown pipelines are not guessed as image models |
| Sequence-classification reranker | `RERANKER` | Registered only; reranker runtime is not connected in this build |
| ASR/TTS model categories | `ASR` / `TTS` when manually represented by future detectors | Registered only; audio runtimes are not connected in this build |

Unverified capabilities are not marked available. Unsupported operation calls return structured errors instead of silently switching models.

## API Examples

Detect:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/models/local/detect \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"path":"/Users/me/models/qwen.gguf"}'
```

Register only:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/models/local/register \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"path":"/Users/me/models/qwen.gguf","capabilities":["CHAT","INFERENCE"],"load":false}'
```

Register and load:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/models/local/register \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"path":"/Users/me/models/qwen.gguf","load":true,"context_length":4096,"gpu_layers":0}'
```

Run chat through the OpenAI-compatible API after loading:

```bash
curl -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer $MF_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen","messages":[{"role":"user","content":"Hello"}]}'
```

Run embeddings for a loaded embedding model:

```bash
curl -X POST http://127.0.0.1:8000/v1/embeddings \
  -H "Authorization: Bearer $MF_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"my-embedder","input":["hello","world"]}'
```

Run a registered local Wan video model:

```bash
curl -X POST http://127.0.0.1:8000/v1/videos \
  -H "Authorization: Bearer $MF_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"local:123","prompt":"A short cinematic test clip","seconds":1,"fps":4,"size":"256x256","num_inference_steps":2}'
```
