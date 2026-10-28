"""Compatibility alias for master contract sync service."""

from app.services.master_contract import (
    import_contracts,
    sync_contracts,
    import_csv,
    list_contracts,
)

__all__ = ["import_contracts", "sync_contracts", "import_csv", "list_contracts"]
