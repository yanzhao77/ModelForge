"""Fine-tuning job runner (standalone CLI entry, runs in a subprocess).

Usage:
    python training_jobs.py --config <cfg.json> --state <state.json> --log <train.log>

Writes progress/loss to the state file and appends human-readable log lines.
Heavy imports (torch/transformers/peft/datasets) happen only inside run(),
so importing this module never pulls the AI stack.
"""
import argparse
import json
import os
import sys


def _write_state(path: str, **kwargs):
    data = {"status": "running"}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data.update(json.load(f))
        except Exception:
            pass
    data.update(kwargs)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _log(msg: str, log_path: str):
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(str(msg) + "\n")


def _load_dataset(dataset_path: str, dataset_format: str):
    from datasets import load_dataset
    if dataset_format == "txt":
        return load_dataset("text", data_files={"train": dataset_path}, split="train")
    return load_dataset(
        "json" if dataset_format in ("jsonl", "json") else dataset_format,
        data_files={"train": dataset_path},
        split="train",
    )


def _preprocess(examples, tokenizer):
    first_key = list(examples.keys())[0]
    texts = []
    for i in range(len(examples[first_key])):
        parts = [str(examples[col][i]) for col in examples.keys()]
        texts.append(" ".join(parts))
    tokenized = tokenizer(texts, truncation=True, padding="max_length", max_length=512)
    tokenized["labels"] = tokenized["input_ids"].copy()
    return tokenized


def _build_progress_callback(state_path: str, log_path: str, total_epochs: int):
    from transformers import TrainerCallback

    class ProgressCallback(TrainerCallback):
        def on_log(self, args, state, control, logs=None, **kwargs):
            logs = logs or {}
            epoch = float(state.epoch or 0)
            progress = min(100.0, epoch / total_epochs * 100.0) if total_epochs else 0
            loss = logs.get("loss")
            _write_state(
                state_path, progress=progress, epoch=int(epoch), loss=loss
            )
            _log(f"epoch {epoch:.2f}/{total_epochs} loss={loss if loss is not None else '-'}", log_path)

    return ProgressCallback()


def run(config: dict, state_path: str, log_path: str):
    _write_state(state_path, status="running", progress=0, epoch=0, loss=None)
    _log(f"加载基础模型: {config['base_model']}", log_path)

    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        Trainer,
        TrainingArguments,
    )

    tokenizer = AutoTokenizer.from_pretrained(config["base_model"])
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(config["base_model"])

    method = config.get("method", "lora")
    if method == "lora":
        from peft import LoraConfig, get_peft_model
        lora_config = LoraConfig(
            r=int(config.get("lora_r", 8)),
            lora_alpha=int(config.get("lora_alpha", 32)),
            target_modules=config.get("target_modules") or ["q_proj", "v_proj"],
            lora_dropout=0.1,
            bias="none",
            task_type="CAUSAL_LM",
        )
        model = get_peft_model(model, lora_config)
        _log(f"LoRA 配置完成 (r={lora_config.r}, alpha={lora_config.lora_alpha})", log_path)
    else:
        _log("全参微调模式", log_path)

    dataset = _load_dataset(config["dataset_path"], config.get("dataset_format", "json"))
    _log(f"数据集加载完成: {len(dataset)} 条", log_path)
    tokenized = dataset.map(
        lambda examples: _preprocess(examples, tokenizer), batched=True
    )

    output_dir = config.get("output_dir", "./outputs")
    os.makedirs(output_dir, exist_ok=True)
    total_epochs = int(config.get("epochs", 3))
    args = TrainingArguments(
        output_dir=output_dir,
        num_train_epochs=total_epochs,
        per_device_train_batch_size=int(config.get("batch_size", 2)),
        learning_rate=float(config.get("learning_rate", 2e-5)),
        logging_steps=5,
        save_strategy="no",
        report_to="none",
    )
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=tokenized,
        tokenizer=tokenizer,
        callbacks=[_build_progress_callback(state_path, log_path, total_epochs)],
    )
    trainer.train()
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)
    _log(f"模型已保存到 {output_dir}", log_path)
    _write_state(state_path, status="done", progress=100)


def main():
    parser = argparse.ArgumentParser(description="ModelForge fine-tuning job")
    parser.add_argument("--config", required=True, help="path to config json")
    parser.add_argument("--state", required=True, help="path to state json")
    parser.add_argument("--log", required=True, help="path to log file")
    args = parser.parse_args()
    with open(args.config, "r", encoding="utf-8") as f:
        config = json.load(f)
    try:
        run(config, args.state, args.log)
    except Exception as e:
        _write_state(args.state, status="error", error=str(e))
        _log(f"训练失败: {e}", args.log)
        sys.exit(1)


if __name__ == "__main__":
    main()