"""Legal transitions for one upload attempt."""
from dataclasses import dataclass, field


ALLOWED = {
    "UPLOADED": {"QUALITY_CHECKING"},
    "QUALITY_CHECKING": {"FORM_VALIDATING", "RECAPTURE_REQUIRED"},
    "FORM_VALIDATING": {"EXTRACTING", "RECAPTURE_REQUIRED"},
    "EXTRACTING": {"VALIDATING", "FAILED"},
    "VALIDATING": {"REVIEW_REQUIRED", "RECAPTURE_REQUIRED"},
    "REVIEW_REQUIRED": {"COMPLETED"},
}


@dataclass
class AttemptState:
    current: str = "UPLOADED"
    history: list[str] = field(default_factory=lambda: ["UPLOADED"])

    def transition(self, target: str) -> None:
        if target not in ALLOWED.get(self.current, set()):
            raise ValueError(f"Invalid processing transition: {self.current} -> {target}")
        self.current = target
        self.history.append(target)
