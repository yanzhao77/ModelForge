import os
import logging
from typing import Dict, List, Any, Optional, Union, Tuple

import torch
from datasets import load_dataset, Dataset, DatasetDict
from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    TrainingArguments,
    Trainer,
    PreTrainedTokenizer,
    PreTrainedModel
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("training.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


class ModelTrainer:
    """模型训练器类，用于管理模型训练流程"""

    def __init__(
            self,
            model_path: str,
            data_file: str,
            output_dir: str = "./results",
            config: Optional[Dict[str, Any]] = None
    ):
        """初始化模型训练器

        Args:
            model_path: 模型路径
            data_file: 数据文件路径
            output_dir: 输出目录
            config: 训练配置参数
        """
        self.model_path = model_path
        self.data_file = data_file
        self.output_dir = output_dir

        # 默认训练配置
        self.config = {
            "eval_strategy": "no",  # 不进行评估
            "save_strategy": "epoch",  # 保存策略按 epoch 进行
            "learning_rate": 2e-5,  # 学习率
            "per_device_train_batch_size": 4,  # 每个设备上的训练批次大小
            "per_device_eval_batch_size": 4,  # 每个设备上的评估批次大小
            "num_train_epochs": 3,  # 训练轮数
            "weight_decay": 0.01,  # 权重衰减
            "logging_dir": './logs',  # 日志目录
            "logging_steps": 10,  # 每多少步记录一次日志
            "save_total_limit": 2,  # 最多保存的检查点数量
            "load_best_model_at_end": False,  # 不加载最佳模型
            "metric_for_best_model": None,  # 不使用指标选择最佳模型
            "greater_is_better": False,  # 损失越低越好
            "report_to": "none",  # 关闭wandb
            "max_length": 512,  # 最大序列长度
        }

        # 更新配置
        if config:
            self.config.update(config)

        # 初始化分词器和模型
        self.tokenizer = None
        self.model = None
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"使用设备: {self.device}")

    def load_tokenizer(self) -> PreTrainedTokenizer:
        """加载分词器

        Returns:
            加载的分词器
        """
        logger.info(f"从 {self.model_path} 加载分词器")
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_path,
            local_files_only=True
        )

        # 确保分词器有 pad_token
        if self.tokenizer.pad_token is None:
            logger.info("分词器没有pad_token，使用eos_token代替")
            self.tokenizer.pad_token = self.tokenizer.eos_token

        return self.tokenizer

    def load_model(self) -> PreTrainedModel:
        """加载模型

        Returns:
            加载的模型
        """
        logger.info(f"从 {self.model_path} 加载模型")
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_path,
            local_files_only=True
        )

        # 确保模型有 pad_token_id
        if self.model.config.pad_token_id is None:
            logger.info("模型没有pad_token_id，使用eos_token_id代替")
            self.model.config.pad_token_id = self.model.config.eos_token_id

        # 将模型移动到设备
        self.model.to(self.device)
        return self.model

    def load_dataset(self) -> DatasetDict:
        """加载数据集

        Returns:
            加载的数据集
        """
        logger.info(f"从 {self.data_file} 加载数据集")
        return load_dataset('json', data_files={'train': self.data_file})

    def preprocess_function(self, examples: Dict[str, List]) -> Dict[str, List]:
        """预处理数据

        Args:
            examples: 数据样本

        Returns:
            处理后的数据
        """
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
        tokenized_inputs = self.tokenizer(
            texts,
            truncation=True,
            padding='max_length',
            max_length=self.config["max_length"]
        )

        # 创建标签，通常是输入序列的移位版本
        labels = tokenized_inputs["input_ids"].copy()
        labels = [
            [-100 if token == self.tokenizer.pad_token_id else token for token in label]
            for label in labels
        ]

        tokenized_inputs["labels"] = labels
        return tokenized_inputs

    def get_training_args(self) -> TrainingArguments:
        """获取训练参数

        Returns:
            训练参数
        """
        return TrainingArguments(
            output_dir=self.output_dir,
            eval_strategy=self.config["eval_strategy"],
            save_strategy=self.config["save_strategy"],
            learning_rate=self.config["learning_rate"],
            per_device_train_batch_size=self.config["per_device_train_batch_size"],
            per_device_eval_batch_size=self.config["per_device_eval_batch_size"],
            num_train_epochs=self.config["num_train_epochs"],
            weight_decay=self.config["weight_decay"],
            logging_dir=self.config["logging_dir"],
            logging_steps=self.config["logging_steps"],
            save_total_limit=self.config["save_total_limit"],
            load_best_model_at_end=self.config["load_best_model_at_end"],
            metric_for_best_model=self.config["metric_for_best_model"],
            greater_is_better=self.config["greater_is_better"],
            report_to=self.config["report_to"],
        )

    def train(self) -> PreTrainedModel:
        """训练模型

        Returns:
            训练后的模型
        """
        # 确保分词器和模型已加载
        if self.tokenizer is None:
            self.load_tokenizer()
        if self.model is None:
            self.load_model()

        # 加载数据集
        dataset_dict = self.load_dataset()

        # 应用预处理
        logger.info("预处理数据集")
        encoded_dataset = dataset_dict.map(
            self.preprocess_function,
            batched=True,
            desc="预处理数据集"
        )

        # 获取训练参数
        training_args = self.get_training_args()

        # 定义训练器
        trainer = CustomTrainer(
            model=self.model,
            args=training_args,
            train_dataset=encoded_dataset['train'],
            tokenizer=self.tokenizer,
        )

        # 开始训练
        logger.info("开始训练模型")
        trainer.train()

        logger.info("训练完成")
        return self.model

    def save_model(self, save_path: Optional[str] = None) -> None:
        """保存模型

        Args:
            save_path: 保存路径，如果为None则使用模型名称
        """
        if self.model is None or self.tokenizer is None:
            raise ValueError("模型或分词器未加载，无法保存")

        # 如果未指定保存路径，使用模型名称
        if save_path is None:
            model_name = os.path.basename(self.model_path)
            save_path = model_name

        logger.info(f"保存模型到 {save_path}")

        # 保存模型和分词器
        self.model.save_pretrained(save_path)
        self.tokenizer.save_pretrained(save_path)

        logger.info(f"模型已保存到 {save_path}")


class CustomTrainer(Trainer):
    """自定义训练器，重写损失计算方法"""

    def compute_loss(
            self,
            model: PreTrainedModel,
            inputs: Dict[str, torch.Tensor],
            return_outputs: bool = False
    ) -> Union[torch.Tensor, Tuple[torch.Tensor, Any]]:
        """计算损失

        Args:
            model: 模型
            inputs: 输入数据
            return_outputs: 是否返回输出

        Returns:
            损失值，或损失值和输出
        """
        labels = inputs.pop("labels")
        outputs = model(**inputs)
        logits = outputs.logits

        # 使用交叉熵损失函数，忽略填充标记
        loss_fct = torch.nn.CrossEntropyLoss(ignore_index=-100)
        loss = loss_fct(logits.view(-1, logits.size(-1)), labels.view(-1))

        return (loss, outputs) if return_outputs else loss


def main():
    """主函数"""
    # 指定本地模型路径
    local_model_path = "E:\\data\\ai_model\\"
    model_name = "Qwen2.5-0.5B"  # 请替换为实际的模型名称
    model_path = os.path.join(local_model_path, model_name)

    # 指定数据文件路径
    data_file = "E:\\data\\ai_datasets\\ruozhiba\\data\\ruozhiba_qa.json"

    # 创建训练器
    trainer = ModelTrainer(
        model_path=model_path,
        data_file=data_file,
        output_dir="./results",
        config={
            "num_train_epochs": 3,
            "learning_rate": 2e-5,
        }
    )

    # 加载分词器和模型
    trainer.load_tokenizer()
    trainer.load_model()

    # 训练模型
    model = trainer.train()

    # 保存模型
    trainer.save_model()


if __name__ == "__main__":
    main()
