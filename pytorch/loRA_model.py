# 安装依赖（首次运行需执行）
# pip install torch transformers datasets peft bitsandbytes

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments, Trainer
from peft import LoraConfig, get_peft_model
from datasets import load_dataset

# 1. 加载夸人数据集（替换为你的CSV路径）
dataset = load_dataset('csv', data_files='quans_data.csv', split='train')

# 2. 初始化模型和Tokenizer（使用7B小模型，消费级GPU可用）
model_name = "meta-llama/Llama-3.1-8B-Instruct"  # 或 mistralai/Mistral-7B-Instruct-v0.2
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForCausalLM.from_pretrained(model_name, device_map="auto", torch_dtype=torch.bfloat16)

# 3. 配置LoRA微调（轻量高效）
lora_config = LoraConfig(
    r=8,

    lora_alpha=32,
    target_modules=["q_proj", "v_proj"],
    lora_dropout=0.1,
    bias="none",
    task_type="CAUSAL_LM"
)
model = get_peft_model(model, lora_config)
model.print_trainable_parameters()  # 输出：17,039,360 可训练参数


# 4. 数据预处理函数
def preprocess_function(examples):
    # 格式化为对话模板（关键！确保模型只输出夸人内容）
    inputs = [
        f"你是一个叫彩虹的夸夸机器人，只负责真诚夸人，绝不讲笑话。用户：{q}\n彩虹小鸡："
        for q in examples["question"]
    ]
    targets = [a for a in examples["answer"]]

    model_inputs = tokenizer(inputs, max_length=256, truncation=True, padding="max_length")
    labels = tokenizer(targets, max_length=256, truncation=True, padding="max_length").input_ids
    model_inputs["labels"] = labels
    return model_inputs


tokenized_dataset = dataset.map(preprocess_function, batched=True)

# 5. 训练参数（消费级GPU友好）
training_args = TrainingArguments(
    output_dir="./quans_model",
    num_train_epochs=3,
    per_device_train_batch_size=2,  # 根据GPU内存调整
    per_device_eval_batch_size=2,
    learning_rate=2e-5,
    weight_decay=0.01,
    warmup_steps=50,
    logging_dir='./logs',
    logging_steps=10,
    save_strategy="epoch",
    evaluation_strategy="epoch",
    fp16=True,  # 使用16位精度节省显存
)

# 6. 启动训练
trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=tokenized_dataset,
    eval_dataset=tokenized_dataset.select(range(10)),  # 用10条验证
)
trainer.train()

# 7. 保存模型（可直接用于对话）
model.save_pretrained("./quans_model")
tokenizer.save_pretrained("./quans_model")

print("✅ 微调完成！模型已保存到 ./quans_model")