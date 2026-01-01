"""
Regression test to ensure audit script never uses non-existent OrderStatusEnum.PENDING
"""
import pytest
import sys
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.models.exchange_order import OrderStatusEnum


def test_pending_does_not_exist():
    """Ensure OrderStatusEnum.PENDING does not exist"""
    assert not hasattr(OrderStatusEnum, "PENDING"), "OrderStatusEnum.PENDING should not exist"


def test_audit_open_statuses_are_valid():
    """Ensure audit script's OPEN_STATUSES only contains valid enum members"""
    # Add scripts directory to path
    scripts_dir = Path(__file__).parent.parent / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    
    # Import OPEN_STATUSES from audit script
    from audit_no_alerts_no_trades import OPEN_STATUSES
    
    # Verify all statuses in OPEN_STATUSES are valid enum members
    valid_enum_members = {OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED,
                          OrderStatusEnum.FILLED, OrderStatusEnum.CANCELLED, OrderStatusEnum.REJECTED,
                          OrderStatusEnum.EXPIRED}
    
    for status in OPEN_STATUSES:
        assert status in valid_enum_members, f"{status} is not a valid OrderStatusEnum member"
        assert isinstance(status, OrderStatusEnum), f"{status} is not an OrderStatusEnum instance"
    
    # Verify PENDING is not in OPEN_STATUSES (it doesn't exist)
    # This will raise AttributeError if we try to access it, which is what we're testing against
    try:
        pending_value = OrderStatusEnum.PENDING
        pytest.fail("OrderStatusEnum.PENDING should not exist")
    except AttributeError:
        pass  # Expected - PENDING doesn't exist
    
    # Verify OPEN_STATUSES contains expected values
    assert OrderStatusEnum.NEW in OPEN_STATUSES, "OPEN_STATUSES should include NEW"
    assert OrderStatusEnum.ACTIVE in OPEN_STATUSES, "OPEN_STATUSES should include ACTIVE"
    assert OrderStatusEnum.PARTIALLY_FILLED in OPEN_STATUSES, "OPEN_STATUSES should include PARTIALLY_FILLED"


def test_audit_open_statuses_count():
    """Verify OPEN_STATUSES has the expected number of statuses"""
    scripts_dir = Path(__file__).parent.parent / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    
    from audit_no_alerts_no_trades import OPEN_STATUSES
    
    # Should have 3 statuses: NEW, ACTIVE, PARTIALLY_FILLED
    assert len(OPEN_STATUSES) == 3, f"OPEN_STATUSES should have 3 statuses, got {len(OPEN_STATUSES)}"

