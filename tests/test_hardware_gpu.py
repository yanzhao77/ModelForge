"""GPU smoke tests intended for an explicit self-hosted NVIDIA runner."""
import pytest


@pytest.mark.gpu
def test_cuda_tensor_roundtrip_on_nvidia_runner():
    torch = pytest.importorskip("torch")
    if not torch.cuda.is_available():
        pytest.skip("NVIDIA CUDA is not available on this runner")
    device = torch.device("cuda")
    value = torch.tensor([1.0, 2.0], device=device)
    assert value.device.type == "cuda"
    assert torch.allclose(value * 2, torch.tensor([2.0, 4.0], device=device))
    torch.cuda.synchronize()
