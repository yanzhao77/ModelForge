"""Stable error mapping for inference and upstream provider failures.

``/chat`` and the RAG ``/knowledge/answer`` route drive the same inference
stack, so they must report the same stable codes. The RAG route used to let an
unreachable provider escape as a bare HTTP 500 while ``/chat`` already answered
``PROVIDER_UNAVAILABLE``; both now share this single classifier.
"""

from __future__ import annotations

import httpx
from core.api_contracts import problem
from core.network_security import ProviderNetworkError
from fastapi import HTTPException
from services.remote_provider_service import RemoteProviderError


class InferenceErrorClassification:
    """Stable code/message/status for one inference failure."""

    def __init__(self, code: str, message: str, http_status: int, retryable: bool):
        self.code = code
        self.message = message
        self.http_status = http_status
        self.retryable = retryable

    def to_problem(self, corr: str) -> HTTPException:
        return problem(self.http_status, self.code, self.message, correlation=corr)

    def to_stream_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


def classify_inference_exception(exc: Exception) -> InferenceErrorClassification:
    """Classify an inference failure into a stable error code."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in {401, 403}:
            return InferenceErrorClassification("AUTHENTICATION_FAILED", "远程服务拒绝认证。请检查 API Key 后重新验证。", 403, False)
        if status == 429:
            return InferenceErrorClassification("RATE_LIMITED", "远程服务正在限流。请稍后由用户手动重试。", 429, True)
        if status in {404, 405, 501}:
            return InferenceErrorClassification("PROTOCOL_UNSUPPORTED", "远程服务不支持当前协议。请切换兼容协议后重新验证。", 400, False)
        if status >= 500:
            return InferenceErrorClassification("PROVIDER_UNAVAILABLE", "远程服务暂时不可用。请稍后由用户手动重试。", 502, True)
        return InferenceErrorClassification("PROVIDER_HTTP_ERROR", "远程服务返回了意外响应。请重新验证模型服务配置。", 502, False)
    if isinstance(exc, httpx.TimeoutException):
        return InferenceErrorClassification("REQUEST_TIMEOUT", "远程服务请求超时。请检查网络或稍后由用户手动重试。", 504, True)
    if isinstance(exc, httpx.RequestError):
        return InferenceErrorClassification("ENDPOINT_UNREACHABLE", "无法连接远程服务。请检查 Base URL 和网络连接。", 502, True)
    if isinstance(exc, RemoteProviderError):
        if getattr(exc, "code", None) == "TARGET_NOT_ALLOWED":
            return InferenceErrorClassification("TARGET_NOT_ALLOWED", "远程服务目标不在允许的网络范围内。", 400, False)
        return InferenceErrorClassification("PROVIDER_CONFIG_INVALID", "远程模型服务配置无效。请检查提供商设置。", 400, False)
    if isinstance(exc, ProviderNetworkError):
        return InferenceErrorClassification("TARGET_NOT_ALLOWED", "远程服务目标不在允许的网络范围内。", 400, False)
    if isinstance(exc, ValueError):
        return InferenceErrorClassification("REQUEST_INVALID", "请求参数无效。请检查输入后重试。", 400, False)
    if isinstance(exc, PermissionError):
        return InferenceErrorClassification("MODEL_ACCESS_DENIED", "无权访问所选模型。请联系管理员。", 403, False)
    return InferenceErrorClassification("INFERENCE_FAILED", "推理请求失败。请稍后重试。", 502, False)
