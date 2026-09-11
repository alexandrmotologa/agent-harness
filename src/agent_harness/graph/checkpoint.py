from pydantic import BaseModel, Field

from ..sandbox.fs_jail import FilesystemJail


class CheckpointMetadata(BaseModel):
    checkpoint_id: str
    node_id: str
    step_index: int
    timestamp: str
    file_manifest: dict[str, str] = Field(default_factory=dict)


class CheckpointManager:
    def __init__(self, jail: FilesystemJail):
        self.jail = jail
        self.checkpoints: dict[str, CheckpointMetadata] = {}

    def capture_checkpoint(self, node_id: str, step_index: int) -> str:
        """Capture workspace snapshot and associate it with a decision node."""
        checkpoint_id = f"ckpt_{step_index}_{node_id[-6:]}"
        manifest = self.jail.save_snapshot(checkpoint_id)

        import datetime
        metadata = CheckpointMetadata(
            checkpoint_id=checkpoint_id,
            node_id=node_id,
            step_index=step_index,
            timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
            file_manifest=manifest,
        )
        self.checkpoints[checkpoint_id] = metadata
        return checkpoint_id

    def restore_checkpoint(self, checkpoint_id: str) -> None:
        """Restore workspace to the state saved at checkpoint_id."""
        self.jail.restore_snapshot(checkpoint_id)

    def get_metadata(self, checkpoint_id: str) -> CheckpointMetadata | None:
        return self.checkpoints.get(checkpoint_id)
