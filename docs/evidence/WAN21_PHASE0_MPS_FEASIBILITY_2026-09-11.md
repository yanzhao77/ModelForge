# Wan2.1 T2V 1.3B Phase 0 MPS Feasibility Evidence - 2026-09-11

## Summary

ModelForge now has an isolated Wan2.1 T2V 1.3B Phase 0 benchmark and resumable snapshot verifier. The local PyTorch/Diffusers environment can import `WanPipeline` and `AutoencoderKLWan`, and an Apple M4 MPS BF16 tensor smoke test passed. The pinned 28.9GB Diffusers snapshot is not complete because the available Hugging Face download path is currently too slow and unstable. No Wan pipeline load or generation scenario has been run. Support classification remains `UNAVAILABLE`.

## Target

- Repository: `Wan-AI/Wan2.1-T2V-1.3B-Diffusers`
- Revision: `0fad780a534b6463e45facd96134c9f345acfa5b`
- Pipeline: `WanPipeline`
- Text encoder: `UMT5EncoderModel` (`google/umt5-xxl` architecture)
- Transformer: `WanTransformer3DModel`
- VAE: `AutoencoderKLWan`
- Scheduler: `UniPCMultistepScheduler`
- Repository files: 31
- Repository bytes from Hugging Face metadata: 28,935,653,511

The “1.3B” name describes the video transformer, not the complete pipeline footprint. The Diffusers repository also contains five text-encoder weight shards totaling approximately 22.7GB on disk.

## Frozen Workload

- Frames: 81
- Resolution: 832x480
- FPS: 15
- Inference steps: 50
- Guidance scale: 5.0
- Seed: 12345
- Transformer/text dtype: BF16
- VAE dtype: FP32
- VAE slicing: enabled
- VAE tiling: enabled
- Default placement: `enable_model_cpu_offload(device="mps")`

The CPU-offload configuration follows the upstream Diffusers usage pattern but remains unverified on this MPS host. CUDA VRAM claims are not used as Apple unified-memory evidence.

## Local Compatibility Preflight

- Diffusers version: `0.40.0`
- `WanPipeline` import: passed
- `AutoencoderKLWan` import: passed
- `torch.backends.mps.is_available()`: true
- BF16 MPS tensor smoke: passed

No dependency installation or upgrade was required for this adaptation.

## Snapshot Acquisition

Command:

```bash
HF_HUB_DISABLE_XET=1 .venv/bin/python \
  benchmarks/wan21_phase0/fetch_and_verify_snapshot.py \
  --workers 12 --chunk-size-mb 32 --retries 5
```

Observed result:

- Intended snapshot root: `benchmarks/wan21_phase0/output/snapshot`
- Download-time verification reached 15/31 repository files, with 16 required files missing
- Approximately 2.4GB of Range chunks existed when acquisition stopped
- Completed/cached Range chunks: 77, totaling 2,583,691,264 bytes
- Official endpoint 1MiB Range probe: approximately 58KB/s over HTTP/1.1
- Official endpoint HTTP/2 probe: approximately 35KB/s
- Mirror 1MiB Range probe: approximately 16KB/s
- Failure observed: peer closed the response before a 32MiB Range body completed

At this throughput, completing and verifying the 28.9GB snapshot during this run was not practical. A later cleanup verification found that the benchmark-local `output/` directory, including the partial Wan chunks and incomplete integrity result, was no longer present. A future attempt must restart snapshot acquisition from zero. Generated/downloaded output remains ignored and must not be committed.

## Benchmark Status

| Scenario | Status | Reason |
|---|---|---|
| `load-only` | Not run | Snapshot incomplete |
| `first` | Not run | `load-only` not passed |
| `warm-repeat` | Not run | First generation not passed |
| `cancel` | Not run | First generation not passed |
| `repeat-three` | Not run | First generation not passed |

## Current Decision

Keep Wan2.1 T2V 1.3B at `UNAVAILABLE` for Apple M4 24GB. Confirmed facts are limited to framework imports, MPS availability, BF16 tensor support, pinned upstream metadata, and partial resumable acquisition. Pipeline loading, CPU offload behavior, peak unified memory, swap growth, output validity, generation time, repeat behavior, and cancellation remain unknown.

## Next Gate

1. Restart the snapshot downloader on a stable/high-throughput connection or place a manually acquired pinned snapshot at the intended path.
2. Require `snapshot_integrity_result.json` to report `complete: true` and `failures: []`.
3. Record a clean pre-run memory/swap baseline.
4. Run `load-only` with the default `model-cpu-offload` placement.
5. Continue to `first` only if load memory and swap evidence are acceptable.

## References

- https://huggingface.co/Wan-AI/Wan2.1-T2V-1.3B-Diffusers
- https://huggingface.co/docs/diffusers/api/pipelines/wan
- https://github.com/Wan-Video/Wan2.1
