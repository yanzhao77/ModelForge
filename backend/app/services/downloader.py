"""Model downloader: background HF/ModelScope downloads with task tracking."""
import asyncio
import time
import uuid

from core.config import settings


class DownloadTask:
    def __init__(self, repo_id: str, filename: str | None = None):
        self.task_id = uuid.uuid4().hex[:12]
        self.repo_id = repo_id
        self.filename = filename
        self.status = "pending"  # pending / running / done / error
        self.progress = 0
        self.message = "等待中"
        self.target_path = None
        self.error = None
        self.created_at = time.time()

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "repo_id": self.repo_id,
            "filename": self.filename,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "target_path": self.target_path,
            "error": self.error,
        }


class Downloader:
    """In-memory download task registry. Persistence can be added later."""

    def __init__(self):
        self._tasks: dict[str, DownloadTask] = {}
        self._semaphore = asyncio.Semaphore(2)

    def start(self, repo_id: str, filename: str | None = None) -> DownloadTask:
        task = DownloadTask(repo_id, filename)
        self._tasks[task.task_id] = task
        asyncio.get_event_loop().create_task(self._run(task))
        return task

    async def _run(self, task: DownloadTask):
        async with self._semaphore:
            task.status = "running"
            task.message = "开始下载..."
            try:
                from huggingface_hub import snapshot_download
                os_env = __import__("os")
                if settings.hf_endpoint:
                    os_env.environ.setdefault("HF_ENDPOINT", settings.hf_endpoint)
                target = os_env.path.join(
                    settings.model_dir, task.repo_id.replace("/", "_")
                )
                os_env.makedirs(target, exist_ok=True)
                kwargs = {"repo_id": task.repo_id, "local_dir": target, "force_download": False}
                if task.filename:
                    kwargs["allow_patterns"] = [task.filename]
                task.message = "下载中（后台）..."
                path = await asyncio.to_thread(snapshot_download, **kwargs)
                task.status = "done"
                task.progress = 100
                task.target_path = str(path)
                task.message = "下载完成"
            except Exception as e:
                task.status = "error"
                task.error = str(e)
                task.message = "下载失败"

    def get(self, task_id: str) -> DownloadTask | None:
        return self._tasks.get(task_id)

    def list(self) -> list:
        return [t.to_dict() for t in sorted(self._tasks.values(), key=lambda x: -x.created_at)]

    def search_hf(self, query: str = "", author: str | None = None, limit: int = 20) -> list:
        """Search HuggingFace for models (GGUF-friendly)."""
        from services.hf_provider import HFProvider
        provider = HFProvider()
        results = provider.list_models(query or "gguf", limit=limit)
        if author:
            results = [r for r in results if author.lower() in str(r.get("author", "")).lower()]
        return results


downloader = Downloader()

def get_downloader() -> Downloader:
    return downloader