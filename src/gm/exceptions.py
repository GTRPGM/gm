from typing import Optional


class PipelineError(Exception):
    """Exception raised when a pipeline node fails."""

    def __init__(
        self,
        node_name: str,
        message: str,
        original_error: Optional[Exception] = None,
        service_name: Optional[str] = None,
    ):
        self.node_name = node_name
        self.message = message
        self.original_error = original_error
        self.service_name = service_name
        super().__init__(self.message)

    def to_dict(self) -> dict:
        return {
            "error_type": "PipelineError",
            "failed_node": self.node_name,
            "failed_service": self.service_name or "Internal",
            "message": self.message,
            "original_error": str(self.original_error) if self.original_error else None,
        }
