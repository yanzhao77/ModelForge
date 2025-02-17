import torch


def check_torch():
    print("PyTorch version:", torch.__version__)

    # 检查CUDA是否可用
    if torch.cuda.is_available():
        print("CUDA is available. Number of GPUs:", torch.cuda.device_count())
        print("Current CUDA device:", torch.cuda.current_device())
        print("CUDA device name:", torch.cuda.get_device_name(torch.cuda.current_device()))
    else:
        print("CUDA is not available.")

    # 创建一个张量，并在可能的情况下将其移动到GPU上
    x = torch.tensor([1.0, 2.0, 3.0])
    print("Original tensor on CPU:\n", x)

    if torch.cuda.is_available():
        x_gpu = x.to('cuda')
        print("Tensor after moving to GPU:\n", x_gpu)


if __name__ == '__main__':
    check_torch()