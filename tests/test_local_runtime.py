"""Tests for local_runtime.py – LocalRuntime (transformers + GGUF)."""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

import pytest

# ---------------------------------------------------------------------------
# Helper: ensure heavy third-party modules are never actually imported
# ---------------------------------------------------------------------------

MOCK_MODULES = {
    "torch": MagicMock(),
    "transformers": MagicMock(),
    "llama_cpp": MagicMock(),
}


def _patch_modules():
    """Return a context-manager that injects mock torch/transformers/llama_cpp."""
    return patch.dict("sys.modules", MOCK_MODULES)


# ---------------------------------------------------------------------------
# Import the module under test (lazy imports inside methods are mocked at call time)
# ---------------------------------------------------------------------------
from services.runtimes.local_runtime import LocalRuntime  # noqa: E402

# ====== __init__ ===========================================================

class TestInit:
    @pytest.fixture(autouse=True)
    def _no_heavy_imports(self):
        with _patch_modules():
            yield

    def test_defaults(self):
        rt = LocalRuntime()
        assert rt.model_path is None
        assert rt._model is None
        assert rt._tokenizer is None
        assert rt._is_gguf is False

    def test_custom_path(self):
        rt = LocalRuntime(model_path="/some/path")
        assert rt.model_path == "/some/path"


# ====== _is_gguf_model =====================================================

class TestIsGgufModel:
    @pytest.fixture(autouse=True)
    def _no_heavy_imports(self):
        with _patch_modules():
            yield

    @patch("os.path.isfile", return_value=True)
    def test_gguf_file(self, mock_isfile):
        assert LocalRuntime._is_gguf_model("model.gguf") is True

    @patch("os.path.isfile", return_value=True)
    def test_non_gguf_file(self, mock_isfile):
        assert LocalRuntime._is_gguf_model("model.bin") is False

    @patch("os.path.isfile", return_value=False)
    @patch("os.path.isdir", return_value=True)
    @patch("os.listdir", return_value=["weights.bin", "model.gguf"])
    def test_directory_with_gguf(self, mock_listdir, mock_isdir, mock_isfile):
        assert LocalRuntime._is_gguf_model("/models/my_model") is True

    @patch("os.path.isfile", return_value=False)
    @patch("os.path.isdir", return_value=True)
    @patch("os.listdir", return_value=["weights.bin", "config.json"])
    def test_directory_without_gguf(self, mock_listdir, mock_isdir, mock_isfile):
        assert LocalRuntime._is_gguf_model("/models/my_model") is False

    @patch("os.path.isfile", return_value=False)
    @patch("os.path.isdir", return_value=False)
    def test_nonexistent_path(self, mock_isdir, mock_isfile):
        assert LocalRuntime._is_gguf_model("/no/such/path") is False


# ====== load ===============================================================

class TestLoadGGUF:
    @pytest.fixture(autouse=True)
    def _setup(self):
        with _patch_modules():
            self.rt = LocalRuntime()
            yield

    @pytest.mark.asyncio
    @patch("os.path.isfile", return_value=True)
    @patch("os.path.isdir", return_value=False)
    async def test_load_gguf_file(self, mock_isdir, mock_isfile):
        mock_llama_cls = MagicMock()
        mock_llama_instance = MagicMock()
        mock_llama_cls.return_value = mock_llama_instance

        with patch.dict("sys.modules", {
            "torch": MagicMock(),
            "transformers": MagicMock(),
            "llama_cpp": MagicMock(Llama=mock_llama_cls),
        }):
            result = await self.rt.load("model.gguf", input_max_length=2048)

        assert result["status"] == "loaded"
        assert self.rt._model is mock_llama_instance
        assert self.rt._tokenizer is None
        assert self.rt._is_gguf is True
        mock_llama_cls.assert_called_once_with(model_path="model.gguf", n_ctx=2048)

    @pytest.mark.asyncio
    @patch("os.path.isfile", return_value=False)
    @patch("os.path.isdir", return_value=True)
    @patch("os.listdir", return_value=["weights.gguf", "config.json"])
    async def test_load_gguf_directory(self, mock_listdir, mock_isdir, mock_isfile):
        mock_llama_cls = MagicMock()
        mock_llama_instance = MagicMock()
        mock_llama_cls.return_value = mock_llama_instance

        with patch.dict("sys.modules", {
            "torch": MagicMock(),
            "transformers": MagicMock(),
            "llama_cpp": MagicMock(Llama=mock_llama_cls),
        }):
            result = await self.rt.load("/models/my_gguf_model")

        assert result["status"] == "loaded"
        assert self.rt._model is mock_llama_instance
        assert self.rt._is_gguf is True
        mock_llama_cls.assert_called_once_with(
            model_path=os.path.join("/models/my_gguf_model", "weights.gguf"),
            n_ctx=4096,
        )

    @pytest.mark.asyncio
    @patch("os.path.isfile", return_value=False)
    @patch("os.path.isdir", return_value=True)
    @patch("os.listdir", return_value=["weights.gguf"])
    async def test_load_gguf_with_model_path_attr(self, mock_listdir, mock_isdir, mock_isfile):
        rt = LocalRuntime(model_path="/preconfigured/model.gguf")
        mock_llama_cls = MagicMock()
        mock_llama_instance = MagicMock()
        mock_llama_cls.return_value = mock_llama_instance

        with patch.dict("sys.modules", {
            "torch": MagicMock(),
            "transformers": MagicMock(),
            "llama_cpp": MagicMock(Llama=mock_llama_cls),
        }):
            result = await rt.load("ignored_name")

        assert result["status"] == "loaded"
        assert rt._model is mock_llama_instance


class TestLoadTransformers:
    @pytest.fixture(autouse=True)
    def _setup(self):
        with _patch_modules():
            self.rt = LocalRuntime()
            yield

    @pytest.mark.asyncio
    @patch("os.path.isfile", return_value=False)
    @patch("os.path.isdir", return_value=True)
    @patch("os.listdir", return_value=["config.json", "model.bin"])
    async def test_load_transformers_cpu(self, mock_listdir, mock_isdir, mock_isfile):
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_model.device = MagicMock()
        mock_model.to.return_value = mock_model
        mock_model.eval = MagicMock()

        mock_auto_tokenizer = MagicMock()
        mock_auto_tokenizer.from_pretrained.return_value = mock_tokenizer
        mock_auto_model = MagicMock()
        mock_auto_model.from_pretrained.return_value = mock_model

        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        mock_torch.float32 = "float32"

        with patch.dict("sys.modules", {
            "torch": mock_torch,
            "transformers": MagicMock(
                AutoModelForCausalLM=mock_auto_model,
                AutoTokenizer=mock_auto_tokenizer,
            ),
            "llama_cpp": MagicMock(),
        }):
            result = await self.rt.load("/models/transformers_model")

        assert result["status"] == "loaded"
        assert self.rt._tokenizer is mock_tokenizer
        assert self.rt._model is mock_model
        assert self.rt._is_gguf is False
        mock_auto_tokenizer.from_pretrained.assert_called_once_with(
            "/models/transformers_model", trust_remote_code=False
        )
        mock_model.eval.assert_called_once()

    @pytest.mark.asyncio
    @patch("os.path.isfile", return_value=False)
    @patch("os.path.isdir", return_value=True)
    @patch("os.listdir", return_value=["config.json"])
    async def test_load_transformers_with_max_length(self, mock_listdir, mock_isdir, mock_isfile):
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_model.device = MagicMock()
        mock_model.to.return_value = mock_model
        mock_model.eval = MagicMock()

        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        mock_torch.float32 = "float32"

        with patch.dict("sys.modules", {
            "torch": mock_torch,
            "transformers": MagicMock(
                AutoModelForCausalLM=MagicMock(return_value=mock_model),
                AutoTokenizer=MagicMock(return_value=mock_tokenizer),
            ),
            "llama_cpp": MagicMock(),
        }):
            result = await self.rt.load("/models/llm", input_max_length=8192)

        assert result["status"] == "loaded"
        assert self.rt._is_gguf is False


# ====== chat ===============================================================

class TestChatGGUF:
    @pytest.fixture(autouse=True)
    def _setup(self):
        with _patch_modules():
            self.rt = LocalRuntime()
            yield

    @pytest.mark.asyncio
    async def test_chat_gguf(self):
        mock_llama_cls = MagicMock()
        mock_llama_instance = MagicMock()
        mock_llama_cls.return_value = mock_llama_instance
        mock_llama_instance.return_value = {
            "choices": [{"text": "  Hello there!  "}],
        }

        with patch.dict("sys.modules", {
            "torch": MagicMock(),
            "transformers": MagicMock(),
            "llama_cpp": MagicMock(Llama=mock_llama_cls),
        }):
            self.rt._model = mock_llama_instance
            self.rt._is_gguf = True
            messages = [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello there!"},
            ]
            result = await self.rt.chat("model.gguf", messages)

        assert result["model"] == "model.gguf"
        assert result["content"] == "Hello there!"
        assert result["raw"] is None
        mock_llama_instance.assert_called_once()
        _, kwargs = mock_llama_instance.call_args
        assert kwargs["max_tokens"] == 2048
        assert kwargs["temperature"] == 0.7
        assert "User:" in kwargs["stop"]

    @pytest.mark.asyncio
    async def test_chat_gguf_custom_params(self):
        mock_llama_instance = MagicMock()
        mock_llama_instance.return_value = {
            "choices": [{"text": "response"}],
        }

        self.rt._model = mock_llama_instance
        self.rt._is_gguf = True
        messages = [{"role": "user", "content": "test"}]
        await self.rt.chat("model.gguf", messages, max_new_tokens=512, temperature=0.2)

        _, kwargs = mock_llama_instance.call_args
        assert kwargs["max_tokens"] == 512
        assert kwargs["temperature"] == 0.2


class TestChatTransformers:
    @pytest.fixture(autouse=True)
    def _setup(self):
        with _patch_modules():
            self.rt = LocalRuntime()
            yield

    @pytest.mark.asyncio
    async def test_chat_transformers(self):
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_model.device = "cpu"

        mock_inputs = MagicMock()
        mock_inputs.to.return_value = mock_inputs
        mock_tokenizer.return_value = mock_inputs

        mock_outputs = MagicMock()
        mock_outputs.__getitem__ = MagicMock(return_value=MagicMock(shape=(1, 10)))
        mock_model.generate.return_value = mock_outputs

        mock_tokenizer.decode.return_value = "User: Hi\nAssistant: Hello back!"

        mock_torch = MagicMock()

        with patch.dict("sys.modules", {
            "torch": mock_torch,
            "transformers": MagicMock(),
            "llama_cpp": MagicMock(),
        }):
            self.rt._model = mock_model
            self.rt._tokenizer = mock_tokenizer
            self.rt._is_gguf = False

            messages = [{"role": "user", "content": "Hi"}]
            result = await self.rt.chat("model", messages, max_new_tokens=1024, temperature=0.5, top_k=30)

        assert result["model"] == "model"
        assert result["content"] == "Hello back!"
        mock_model.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_chat_auto_loads(self):
        mock_llama_cls = MagicMock()
        mock_llama_instance = MagicMock()
        mock_llama_cls.return_value = mock_llama_instance
        mock_llama_instance.return_value = {
            "choices": [{"text": "auto-loaded response"}],
        }

        with patch("os.path.isfile", return_value=True), \
             patch("os.path.isdir", return_value=False), \
             patch.dict("sys.modules", {
                 "torch": MagicMock(),
                 "transformers": MagicMock(),
                 "llama_cpp": MagicMock(Llama=mock_llama_cls),
             }):
            rt = LocalRuntime()
            messages = [{"role": "user", "content": "Hey"}]
            result = await rt.chat("model.gguf", messages)

        assert result["model"] == "model.gguf"
        assert result["content"] == "auto-loaded response"
        assert rt._model is mock_llama_instance


# ====== stop ===============================================================

class TestStop:
    @pytest.fixture(autouse=True)
    def _setup(self):
        with _patch_modules():
            self.rt = LocalRuntime()
            yield

    @pytest.mark.asyncio
    async def test_stop_with_gguf_model(self):
        mock_model = MagicMock()
        self.rt._model = mock_model
        self.rt._is_gguf = True

        result = await self.rt.stop("model.gguf")
        assert result["status"] == "stopped"
        assert result["model"] == "model.gguf"
        assert self.rt._model is None

    @pytest.mark.asyncio
    async def test_stop_with_transformers_model(self):
        mock_model = MagicMock()
        self.rt._model = mock_model
        self.rt._is_gguf = False

        result = await self.rt.stop("model")
        assert result["status"] == "stopped"
        mock_model.to.assert_called_once_with("cpu")
        assert self.rt._model is None

    @pytest.mark.asyncio
    async def test_stop_no_model(self):
        result = await self.rt.stop("model")
        assert result["status"] == "stopped"
        assert self.rt._model is None

    @pytest.mark.asyncio
    async def test_stop_with_tokenizer(self):
        mock_tokenizer = MagicMock()
        self.rt._tokenizer = mock_tokenizer

        result = await self.rt.stop("model")
        assert result["status"] == "stopped"
        assert self.rt._tokenizer is None

    @pytest.mark.asyncio
    async def test_stop_exception_handled(self):
        mock_model = MagicMock()
        mock_model.to.side_effect = RuntimeError("GPU error")
        self.rt._model = mock_model
        self.rt._is_gguf = False

        result = await self.rt.stop("model")
        assert result["status"] == "stopped"

    @pytest.mark.asyncio
    async def test_stop_del_exception(self):
        class BadDel:
            def __del__(self):
                raise RuntimeError("cleanup failed")

        self.rt._model = BadDel()
        result = await self.rt.stop("model")
        assert result["status"] == "stopped"


# ====== _build_prompt ======================================================

class TestBuildPrompt:
    def test_single_user_message(self):
        msgs = [{"role": "user", "content": "Hello"}]
        assert LocalRuntime._build_prompt(msgs) == "User: Hello\nAssistant: "

    def test_user_and_assistant(self):
        msgs = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hey there!"},
        ]
        expected = "User: Hi\nAssistant: Hey there!\nAssistant: "
        assert LocalRuntime._build_prompt(msgs) == expected

    def test_multi_turn(self):
        msgs = [
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
            {"role": "user", "content": "Q2"},
        ]
        expected = "User: Q1\nAssistant: A1\nUser: Q2\nAssistant: "
        assert LocalRuntime._build_prompt(msgs) == expected

    def test_missing_content(self):
        msgs = [{"role": "user"}]
        assert LocalRuntime._build_prompt(msgs) == "User: \nAssistant: "

    def test_unknown_role(self):
        msgs = [{"role": "system", "content": "Be helpful"}]
        assert LocalRuntime._build_prompt(msgs) == "Assistant: Be helpful\nAssistant: "

    def test_empty_messages(self):
        assert LocalRuntime._build_prompt([]) == "Assistant: "


# ====== _release_response ==================================================

class TestReleaseResponse:
    def test_no_user_marker(self):
        assert LocalRuntime._release_response("Hello Assistant!") == "Hello Assistant!"

    def test_no_user_marker_strips_whitespace(self):
        assert LocalRuntime._release_response("  spaced out  ") == "spaced out"

    def test_user_marker_no_assistant_after(self):
        full = "User: Hi\nSomething else"
        assert LocalRuntime._release_response(full) == "Hi\nSomething else"

    def test_user_and_assistant_markers(self):
        full = "User: Hi\nAssistant: Hello!"
        assert LocalRuntime._release_response(full) == "Hello!"

    def test_user_and_assistant_with_prefix(self):
        full = "User: Hi\nAssistant: Hello!\nMore text"
        assert LocalRuntime._release_response(full) == "Hello!\nMore text"

    def test_multiple_user_markers(self):
        full = "User: Q1\nAssistant: A1\nUser: Q2\nAssistant: A2"
        assert LocalRuntime._release_response(full) == "A2"

    def test_last_user_no_following_assistant(self):
        full = "User: Q1\nAssistant: A1\nUser: Q2\nwaiting..."
        assert LocalRuntime._release_response(full) == "Q2\nwaiting..."
