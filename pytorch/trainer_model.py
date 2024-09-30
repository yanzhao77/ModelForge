import os

import torch
from datasets import load_dataset
from transformers import AutoTokenizer, AutoModelForCausalLM, TrainingArguments, Trainer

# 指定本地模型路径
local_model_path = "E:\\data\\ai_model\\"
model_name = "Qwen2.5-0.5B"  # 请替换为实际的模型名称
model_path = os.path.join(local_model_path, model_name)

# 加载分词器
tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)

# 指定数据文件路径
# data_file = "E:\\data\\ai_datasets\\Beautiful-Chinese\\Beautiful-Chinese2.jsonl"
# data_file = "E:\\data\\ai_datasets\\ruozhiba\\data\\ruozhiba-post-annual2.json"
# data_file = "E:\\data\\ai_datasets\\Muice-Dataset\\wikihow.jsonl"
data_file = "E:\\data\\ai_datasets\\ruozhiba\\data\\ruozhiba_qa.json"
# 加载数据
dataset_dict = load_dataset('json', data_files={
    'train': data_file,
})

training_output_dir = "./results",
training_eval_strategy = "no",  # 不进行评估
training_save_strategy = "epoch",  # 保存策略按 epoch 进行
training_learning_rate = 2e-5,  # 学习率
training_per_device_train_batch_size = 4,  # 每个设备上的训练批次大小
training_per_device_eval_batch_size = 4,  # 每个设备上的评估批次大小
training_num_train_epochs = 3,  # 训练轮数
training_weight_decay = 0.01,  # 权重衰减
training_logging_dir = './logs',  # 日志目录
training_logging_steps = 10,  # 每多少步记录一次日志
training_save_total_limit = 2,  # 最多保存的检查点数量
training_load_best_model_at_end = False,  # 不加载最佳模型
training_metric_for_best_model = None,  # 不使用指标选择最佳模型
training_greater_is_better = False,  # 损失越低越好
training_report_to = "none",  # 关闭wandb


# 预处理函数
def preprocess_function(examples):
    # 获取所有的列名
    column_names = examples.pa_table.column_names

    # 初始化一个空列表来存储拼接后的文本
    texts = []

    # 遍历每个样本
    for i in range(len(examples[column_names[0]])):
        # 对于每个样本，从每一列中提取值并拼接
        text_parts = [str(examples[col][i]) for col in column_names]
        # 将所有部分拼接成一个字符串
        text = ' '.join(text_parts)
        texts.append(text)

    # 使用分词器进行编码，并设置 padding 和 truncation
    tokenized_inputs = tokenizer(texts, truncation=True, padding='max_length', max_length=512)

    # 创建标签，通常是输入序列的移位版本
    labels = tokenized_inputs["input_ids"].copy()
    labels = [[-100 if token == tokenizer.pad_token_id else token for token in label] for label in labels]

    tokenized_inputs["labels"] = labels
    return tokenized_inputs


def train_model():
    # 应用预处理
    encoded_dataset = dataset_dict.map(preprocess_function, batched=True)

    # 设置训练参数
    training_args = TrainingArguments(
        output_dir=training_output_dir,
        eval_strategy=training_eval_strategy,  # 不进行评估
        save_strategy=training_save_strategy,  # 保存策略按 epoch 进行
        learning_rate=training_learning_rate,  # 学习率
        per_device_train_batch_size=training_per_device_train_batch_size,  # 每个设备上的训练批次大小
        per_device_eval_batch_size=training_per_device_eval_batch_size,  # 每个设备上的评估批次大小
        num_train_epochs=training_num_train_epochs,  # 训练轮数
        weight_decay=training_weight_decay,  # 权重衰减
        logging_dir=training_logging_dir,  # 日志目录
        logging_steps=training_logging_steps,  # 每多少步记录一次日志
        save_total_limit=training_save_total_limit,  # 最多保存的检查点数量
        load_best_model_at_end=training_load_best_model_at_end,  # 不加载最佳模型
        metric_for_best_model=training_metric_for_best_model,  # 不使用指标选择最佳模型
        greater_is_better=training_greater_is_better,  # 损失越低越好
        report_to=training_report_to,  # 关闭wandb
        # remove_unused_columns=False,  # 防止自动删除未使用的列,这个加上莫名其妙老是报ValueError
    )

    # 加载预训练模型
    model = AutoModelForCausalLM.from_pretrained(model_path, local_files_only=True)

    # 如果模型没有设置 pad_token_id，手动设置
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    if model.config.pad_token_id is None:
        model.config.pad_token_id = model.config.eos_token_id

    # 确保模型和数据都在 CPU 或 GPU 上运行
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    # 定义训练器
    trainer = CustomTrainer(
        model=model,
        args=training_args,
        train_dataset=encoded_dataset['train'],
        # 如果有验证集，可以添加
        # eval_dataset=encoded_dataset['validation'],
        tokenizer=tokenizer,
    )
    # 开始训练
    trainer.train()
    return model


def save_model(model):
    # 保存最终模型
    output_dir = "Qwen2.5-0.5B"
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)

    print(f"模型已保存到 {output_dir}")


# 自定义 compute_loss 方法
class CustomTrainer(Trainer):
    def compute_loss(self, model, inputs, return_outputs=False):
        labels = inputs.pop("labels")
        outputs = model(**inputs)
        logits = outputs.logits
        loss_fct = torch.nn.CrossEntropyLoss(ignore_index=-100)
        loss = loss_fct(logits.view(-1, logits.size(-1)), labels.view(-1))
        return (loss, outputs) if return_outputs else loss
