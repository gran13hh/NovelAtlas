"""Task-local structured telemetry, without prompts, responses or credentials."""

import json
import time
from datetime import UTC, datetime
from uuid import uuid4

import tiktoken

from novelatlas.services.temporary_storage import TemporaryUploadStorage


class Trace:
    def __init__(self, storage: TemporaryUploadStorage, task_id: str):
        self.storage, self.task_id = storage, task_id

    def emit(self, kind: str, **fields):
        self.storage.get(self.task_id)
        record = {"time": datetime.now(UTC).isoformat(), "kind": kind, **fields}
        self.storage.write_json_artifact(
            self.task_id, "trace-" + uuid4().hex, json.dumps(record, ensure_ascii=False)
        )

    def records(self):
        self.storage.get(self.task_id)
        root = self.storage.source_path(self.task_id).parent
        return sorted(
            (json.loads(p.read_text()) for p in root.glob("trace-*.json")),
            key=lambda r: r["time"],
        )


class TracedGateway:
    def __init__(self, gateway, trace: Trace, tokenizer: str):
        self.gateway, self.trace, self.tokenizer = gateway, trace, tokenizer
        self.text_config = gateway.text_config

    async def generate_text(self, request):
        start = time.perf_counter()
        estimate = len(
            tiktoken.get_encoding(self.tokenizer).encode_ordinary(
                request.prompt + (request.instructions or "")
            )
        )
        gateway = self.gateway
        if hasattr(gateway, "with_observer"):
            call_id = uuid4().hex
            gateway = gateway.with_observer(
                lambda event: self.trace.emit(
                    "provider_attempt", call_id=call_id, **event
                )
            )
        try:
            result = await gateway.generate_text(request)
        except BaseException as error:
            self.trace.emit(
                "model",
                status="failed",
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                estimated_input_tokens=estimate,
                error_code=getattr(error, "code", type(error).__name__),
            )
            raise
        self.trace.emit(
            "model",
            status="completed",
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
            estimated_input_tokens=estimate,
            measured_usage=result.usage.model_dump()
            if result.usage and not result.is_mock
            else None,
            mock_usage=result.usage.model_dump()
            if result.usage and result.is_mock
            else None,
            request_id=result.request_id,
        )
        return result
