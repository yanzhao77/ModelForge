"""Tests for training_jobs module (DEV-006 coverage)."""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "backend" / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

# Mock heavy dependencies before importing
mock_transformers = MagicMock()
mock_peft = MagicMock()
mock_datasets = MagicMock()

# Set up the mock modules
sys.modules["transformers"] = mock_transformers
sys.modules["transformers.TrainerCallback"] = MagicMock()
sys.modules["transformers.Trainer"] = MagicMock()
sys.modules["transformers.TrainingArguments"] = MagicMock()
sys.modules["transformers.AutoTokenizer"] = MagicMock()
sys.modules["transformers.AutoModelForCausalLM"] = MagicMock()
sys.modules["peft"] = mock_peft
sys.modules["peft.LoraConfig"] = MagicMock()
sys.modules["peft.get_peft_model"] = MagicMock()
sys.modules["datasets"] = mock_datasets
sys.modules["datasets.load_dataset"] = MagicMock()

# Now import the module with mocks in place
import services.runtimes.training_jobs as training_jobs_module

importlib.reload(training_jobs_module)

from services.runtimes.training_jobs import (
    _build_progress_callback,
    _load_dataset,
    _preprocess,
    _write_state,
    main,
    run,
)


class TestTrainingJobsHelpers:
    """Test helper functions in training_jobs."""

    def test_write_state_creates_file(self, tmp_path):
        """Test _write_state creates state file."""
        state_path = tmp_path / "state.json"
        _write_state(str(state_path), status="running", progress=50)
        assert state_path.exists()
        data = json.loads(state_path.read_text())
        assert data["status"] == "running"
        assert data["progress"] == 50

    def test_write_state_updates_existing(self, tmp_path):
        """Test _write_state updates existing file."""
        state_path = tmp_path / "state.json"
        _write_state(str(state_path), status="running", progress=0)
        _write_state(str(state_path), progress=100, loss=0.5)
        data = json.loads(state_path.read_text())
        assert data["status"] == "running"
        assert data["progress"] == 100
        assert data["loss"] == 0.5

    def test_load_dataset_jsonl(self, tmp_path):
        """Test loading JSONL dataset."""
        # Create test file
        data_file = tmp_path / "data.jsonl"
        data_file.write_text('{"text": "hello"}\n{"text": "world"}')

        # Mock datasets.load_dataset (imported locally in the function)
        with patch("datasets.load_dataset") as mock_load:
            mock_dataset = MagicMock()
            mock_dataset.__len__ = MagicMock(return_value=2)
            mock_load.return_value = mock_dataset

            _load_dataset(str(data_file), "jsonl")
            mock_load.assert_called_once()

    def test_load_dataset_json(self, tmp_path):
        """Test loading JSON dataset."""
        data_file = tmp_path / "data.json"
        data_file.write_text('[{"text": "hello"}, {"text": "world"}]')

        with patch("datasets.load_dataset") as mock_load:
            mock_dataset = MagicMock()
            mock_dataset.__len__ = MagicMock(return_value=2)
            mock_load.return_value = mock_dataset

            _load_dataset(str(data_file), "json")
            mock_load.assert_called_once()

    def test_load_dataset_txt(self, tmp_path):
        """Test loading text dataset."""
        data_file = tmp_path / "data.txt"
        data_file.write_text("hello\nworld")

        with patch("datasets.load_dataset") as mock_load:
            mock_dataset = MagicMock()
            mock_dataset.__len__ = MagicMock(return_value=2)
            mock_load.return_value = mock_dataset

            _load_dataset(str(data_file), "txt")
            mock_load.assert_called_once()

    def test_preprocess(self):
        """Test _preprocess tokenization."""
        # Mock tokenizer
        mock_tokenizer = MagicMock()
        mock_tokenizer.return_value = {
            "input_ids": [[1, 2, 3], [4, 5, 6]],
            "attention_mask": [[1, 1, 1], [1, 1, 1]],
        }

        examples = {"text": ["hello world", "foo bar"]}
        result = _preprocess(examples, mock_tokenizer)

        assert "input_ids" in result
        assert "labels" in result
        assert result["labels"] == result["input_ids"]  # Labels copied from input_ids

    def test_build_progress_callback(self, tmp_path):
        """Test _build_progress_callback creates callback."""
        state_path = tmp_path / "state.json"
        log_path = tmp_path / "train.log"

        # The function imports transformers internally, so we need to mock it in sys.modules
        import sys
        from unittest.mock import MagicMock
        mock_transformers = MagicMock()
        mock_trainer_callback = MagicMock()
        mock_transformers.TrainerCallback = mock_trainer_callback
        original_transformers = sys.modules.get("transformers")
        sys.modules["transformers"] = mock_transformers
        try:
            callback = _build_progress_callback(str(state_path), str(log_path), 3)
            assert hasattr(callback, "on_log")
            # The callback should be an instance of the generated class
            assert callback is not None
        finally:
            if original_transformers is not None:
                sys.modules["transformers"] = original_transformers
            else:
                del sys.modules["transformers"]


class TestTrainingJobsRun:
    """Test the run function with mocked heavy dependencies."""

    def test_run_loads_model(self, tmp_path):
        """Test run function loads model and tokenizer."""
        config = {
            "base_model": "test-model",
            "dataset_path": str(tmp_path / "data.jsonl"),
            "output_dir": str(tmp_path / "outputs"),
            "method": "lora",
            "lora_r": 8,
            "lora_alpha": 32,
            "target_modules": ["q_proj", "v_proj"],
            "epochs": 1,
            "batch_size": 1,
            "learning_rate": 2e-5,
        }
        state_path = tmp_path / "state.json"
        log_path = tmp_path / "train.log"

        # Mock all heavy imports via sys.modules
        import sys
        from unittest.mock import MagicMock

        mock_transformers = MagicMock()
        mock_peft = MagicMock()
        mock_datasets = MagicMock()

        mock_tokenizer = MagicMock()
        mock_tokenizer.pad_token = None
        mock_tokenizer.eos_token = "<eos>"
        mock_transformers.AutoTokenizer = MagicMock()
        mock_transformers.AutoTokenizer.from_pretrained.return_value = mock_tokenizer
        mock_transformers.AutoModelForCausalLM = MagicMock()
        mock_transformers.AutoModelForCausalLM.from_pretrained.return_value = MagicMock()
        mock_transformers.Trainer = MagicMock()
        mock_transformers.TrainingArguments = MagicMock()

        mock_peft.LoraConfig = MagicMock()
        mock_peft.get_peft_model = MagicMock(return_value=MagicMock())

        mock_datasets.load_dataset = MagicMock(return_value=MagicMock(__len__=MagicMock(return_value=10)))

        original_transformers = sys.modules.get("transformers")
        original_peft = sys.modules.get("peft")
        original_datasets = sys.modules.get("datasets")

        sys.modules["transformers"] = mock_transformers
        sys.modules["peft"] = mock_peft
        sys.modules["datasets"] = mock_datasets

        try:
            run(config, str(state_path), str(log_path))

            # Verify model loading
            mock_transformers.AutoTokenizer.from_pretrained.assert_called_once_with("test-model")
            mock_transformers.AutoModelForCausalLM.from_pretrained.assert_called_once_with("test-model")
            mock_peft.get_peft_model.assert_called_once()

            # Verify training
            mock_transformers.Trainer.return_value.train.assert_called_once()
            mock_peft.get_peft_model.return_value.save_pretrained.assert_called_once()
            mock_tokenizer.save_pretrained.assert_called_once()

            # Verify state file
            assert state_path.exists()
            state = json.loads(state_path.read_text())
            assert state["status"] == "done"
            assert state["progress"] == 100
        finally:
            if original_transformers is not None:
                sys.modules["transformers"] = original_transformers
            else:
                del sys.modules["transformers"]
            if original_peft is not None:
                sys.modules["peft"] = original_peft
            else:
                del sys.modules["peft"]
            if original_datasets is not None:
                sys.modules["datasets"] = original_datasets
            else:
                del sys.modules["datasets"]

    def test_run_full_finetune(self, tmp_path):
        """Test run function with full fine-tuning (not LoRA)."""
        config = {
            "base_model": "test-model",
            "dataset_path": str(tmp_path / "data.jsonl"),
            "output_dir": str(tmp_path / "outputs"),
            "method": "full",
            "epochs": 1,
        }
        state_path = tmp_path / "state.json"
        log_path = tmp_path / "train.log"

        import sys
        from unittest.mock import MagicMock

        mock_transformers = MagicMock()
        mock_peft = MagicMock()
        mock_datasets = MagicMock()

        mock_tokenizer = MagicMock()
        mock_tokenizer.pad_token = None
        mock_tokenizer.eos_token = "<eos>"
        mock_transformers.AutoTokenizer = MagicMock()
        mock_transformers.AutoTokenizer.from_pretrained.return_value = mock_tokenizer
        mock_transformers.AutoModelForCausalLM = MagicMock()
        mock_transformers.AutoModelForCausalLM.from_pretrained.return_value = MagicMock()
        mock_transformers.Trainer = MagicMock()
        mock_transformers.TrainingArguments = MagicMock()

        mock_peft.LoraConfig = MagicMock()
        mock_peft.get_peft_model = MagicMock(return_value=MagicMock())

        mock_datasets.load_dataset = MagicMock(return_value=MagicMock(__len__=MagicMock(return_value=10)))

        original_transformers = sys.modules.get("transformers")
        original_peft = sys.modules.get("peft")
        original_datasets = sys.modules.get("datasets")

        sys.modules["transformers"] = mock_transformers
        sys.modules["peft"] = mock_peft
        sys.modules["datasets"] = mock_datasets

        try:
            run(config, str(state_path), str(log_path))

            # Verify model loading
            mock_transformers.AutoTokenizer.from_pretrained.assert_called_once_with("test-model")
            mock_transformers.AutoModelForCausalLM.from_pretrained.assert_called_once_with("test-model")
            # Verify get_peft_model was NOT called
            mock_peft.get_peft_model.assert_not_called()

            # Verify training
            mock_transformers.Trainer.return_value.train.assert_called_once()
            mock_tokenizer.save_pretrained.assert_called_once()

            # Verify state file
            assert state_path.exists()
            state = json.loads(state_path.read_text())
            assert state["status"] == "done"
            assert state["progress"] == 100
        finally:
            if original_transformers is not None:
                sys.modules["transformers"] = original_transformers
            else:
                del sys.modules["transformers"]
            if original_peft is not None:
                sys.modules["peft"] = original_peft
            else:
                del sys.modules["peft"]
            if original_datasets is not None:
                sys.modules["datasets"] = original_datasets
            else:
                del sys.modules["datasets"]

    def test_run_error_handling(self, tmp_path):
        """Test run function raises exceptions on error."""
        config = {
            "base_model": "test-model",
            "dataset_path": str(tmp_path / "data.jsonl"),
            "output_dir": str(tmp_path / "outputs"),
        }
        state_path = tmp_path / "state.json"
        log_path = tmp_path / "train.log"

        import sys
        from unittest.mock import MagicMock

        mock_transformers = MagicMock()
        mock_peft = MagicMock()
        mock_datasets = MagicMock()

        mock_transformers.AutoTokenizer = MagicMock()
        mock_transformers.AutoTokenizer.from_pretrained.side_effect = Exception("Model not found")
        mock_transformers.AutoModelForCausalLM = MagicMock()
        mock_transformers.Trainer = MagicMock()
        mock_transformers.TrainingArguments = MagicMock()

        mock_peft.LoraConfig = MagicMock()
        mock_peft.get_peft_model = MagicMock()

        mock_datasets.load_dataset = MagicMock(return_value=MagicMock(__len__=MagicMock(return_value=10)))

        original_transformers = sys.modules.get("transformers")
        original_peft = sys.modules.get("peft")
        original_datasets = sys.modules.get("datasets")

        sys.modules["transformers"] = mock_transformers
        sys.modules["peft"] = mock_peft
        sys.modules["datasets"] = mock_datasets

        try:
            with pytest.raises(Exception, match="Model not found"):
                run(config, str(state_path), str(log_path))
        finally:
            if original_transformers is not None:
                sys.modules["transformers"] = original_transformers
            else:
                del sys.modules["transformers"]
            if original_peft is not None:
                sys.modules["peft"] = original_peft
            else:
                del sys.modules["peft"]
            if original_datasets is not None:
                sys.modules["datasets"] = original_datasets
            else:
                del sys.modules["datasets"]

    def test_run_cancelled_via_state(self, tmp_path):
        """Test run function respects cancellation via state file."""
        config = {
            "base_model": "test-model",
            "dataset_path": str(tmp_path / "data.jsonl"),
            "output_dir": str(tmp_path / "outputs"),
        }
        state_path = tmp_path / "state.json"
        log_path = tmp_path / "train.log"

        import sys
        from unittest.mock import MagicMock

        mock_transformers = MagicMock()
        mock_peft = MagicMock()
        mock_datasets = MagicMock()

        mock_transformers.AutoTokenizer = MagicMock()
        mock_transformers.AutoTokenizer.from_pretrained.side_effect = KeyboardInterrupt("Cancelled")
        mock_transformers.AutoModelForCausalLM = MagicMock()
        mock_transformers.Trainer = MagicMock()
        mock_transformers.TrainingArguments = MagicMock()

        mock_peft.LoraConfig = MagicMock()
        mock_peft.get_peft_model = MagicMock()

        mock_datasets.load_dataset = MagicMock(return_value=MagicMock(__len__=MagicMock(return_value=10)))

        original_transformers = sys.modules.get("transformers")
        original_peft = sys.modules.get("peft")
        original_datasets = sys.modules.get("datasets")

        sys.modules["transformers"] = mock_transformers
        sys.modules["peft"] = mock_peft
        sys.modules["datasets"] = mock_datasets

        try:
            with pytest.raises(KeyboardInterrupt):
                run(config, str(state_path), str(log_path))

            assert state_path.exists()
        finally:
            if original_transformers is not None:
                sys.modules["transformers"] = original_transformers
            else:
                del sys.modules["transformers"]
            if original_peft is not None:
                sys.modules["peft"] = original_peft
            else:
                del sys.modules["peft"]
            if original_datasets is not None:
                sys.modules["datasets"] = original_datasets
            else:
                del sys.modules["datasets"]


class TestTrainingJobsMain:
    """Test the main CLI entry point."""

    def test_main_success(self, tmp_path):
        """Test main function on success."""
        config = {
            "base_model": "test-model",
            "dataset_path": str(tmp_path / "data.jsonl"),
            "output_dir": str(tmp_path / "outputs"),
        }
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config))
        state_path = tmp_path / "state.json"
        log_path = tmp_path / "train.log"

        with patch("services.runtimes.training_jobs.run") as mock_run:
            sys.argv = ["training_jobs.py", "--config", str(config_path), "--state", str(state_path), "--log", str(log_path)]
            main()
            mock_run.assert_called_once()

    def test_main_error_exit_code(self, tmp_path):
        """Test main exits with code 1 on error."""
        config = {
            "base_model": "test-model",
            "dataset_path": str(tmp_path / "data.jsonl"),
            "output_dir": str(tmp_path / "outputs"),
        }
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config))
        state_path = tmp_path / "state.json"
        log_path = tmp_path / "train.log"

        with patch("services.runtimes.training_jobs.run", side_effect=Exception("fail")):
            sys.argv = ["training_jobs.py", "--config", str(config_path), "--state", str(state_path), "--log", str(log_path)]
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1