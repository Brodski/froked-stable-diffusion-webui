pip install torch==2.7.0 torchvision==0.22.0 --index-url https://download.pytorch.org/whl/cu128 --extra-index-url https://pypi.org/simple
pip install torch==2.7.0 torchvision==0.22.0 --index-url https://download.pytorch.org/whl/cu128


import torch
print(torch.__version__, torch.version.cuda)     # expect 2.7.0 12.8
print(torch.cuda.get_device_name(0))             # NVIDIA GeForce RTX 5080
print(torch.cuda.get_device_capability(0))       # (12, 0)


A1111

.\venv\Scripts\activate
 python .\launch.py 


