import json
import os

from datasets import Dataset, DatasetDict
from modelscope import MsDataset

local_ds_path = "E:\\data\\ai_datasets\\"
ds_name = "ruozhiba\\dataset_infos.json"
ds_path = os.path.join(local_ds_path, ds_name)

dataset_dict = MsDataset.load(ds_path, subset_name='post-annual', split='train')

print(dataset_dict)


# 读取 JSON 文件
with open(ds_path, 'r', encoding='utf-8') as f:
    data = [json.loads(line) for line in f]

# 将数据转换为 Dataset 对象
dataset = Dataset.from_list(data)

# 创建 DatasetDict
dataset_dict = DatasetDict({
    'train': dataset,
    # 如果有验证集和测试集，也可以添加
    # 'validation': validation_dataset,
    # 'test': test_dataset
})

print(dataset_dict)