# Wan2.1 T2V 1.3B Phase 0

This benchmark is isolated from production ModelForge code. It targets:

- Model: `Wan-AI/Wan2.1-T2V-1.3B-Diffusers`
- Revision: `0fad780a534b6463e45facd96134c9f345acfa5b`
- Pipeline: `WanPipeline`
- Transformer/text dtype: BF16
- VAE dtype: FP32
- Workload: 81 frames, 832x480, 15 FPS, 50 steps, guidance scale 5.0
- Default placement: component-level CPU offload to MPS

Download and verify the pinned snapshot:

```bash
HF_HUB_DISABLE_XET=1 .venv/bin/python \
  benchmarks/wan21_phase0/fetch_and_verify_snapshot.py
```

The downloader uses resumable Range chunks. Re-running the same command keeps completed chunks and verifies every LFS file with its SHA-256 etag before publishing it.

Inspect an interrupted snapshot without making network requests:

```bash
.venv/bin/python benchmarks/wan21_phase0/fetch_and_verify_snapshot.py --verify-only
```

After `snapshot_integrity_result.json` reports `complete: true`, run one scenario at a time with network access disabled:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python \
  benchmarks/wan21_phase0/phase0_wan21_benchmark.py \
  --scenario load-only
```

Continue with `first`, `warm-repeat`, `cancel`, and `repeat-three` only after reviewing the preceding result's memory and swap evidence. Do not set `PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.0`.
