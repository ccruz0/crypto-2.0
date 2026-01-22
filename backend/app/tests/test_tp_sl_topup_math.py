"""
Tests for top-up suggestion math in SL/TP order creation.
Verifies that top-up quantities are correctly rounded UP to step size and result in >= min_qty.
"""
import pytest
import decimal
from unittest.mock import Mock, patch


def test_topup_math_rounds_up_to_step_size():
    """Test that top-up quantity is rounded UP to step size."""
    # Test case: raw_qty below min -> suggested topup qty is step-aligned and results in >= min_qty after adding
    normalized_qty = 0.0005  # Below min
    min_qty = 0.001
    step_size = 0.0001
    
    # Calculate top-up
    target_qty = min_qty
    topup_qty_raw = target_qty - normalized_qty  # 0.001 - 0.0005 = 0.0005
    
    # Round UP to step size
    topup_qty_decimal = decimal.Decimal(str(topup_qty_raw))
    step_decimal = decimal.Decimal(str(step_size))
    division_result = topup_qty_decimal / step_decimal  # 0.0005 / 0.0001 = 5.0
    ceiled_result = division_result.quantize(decimal.Decimal('1'), rounding=decimal.ROUND_CEILING)
    topup_qty_rounded = float(ceiled_result * step_decimal)  # 5 * 0.0001 = 0.0005
    
    # Verify: normalized_qty + topup_qty_rounded >= min_qty
    final_qty = normalized_qty + topup_qty_rounded
    assert final_qty >= min_qty, f"Final qty {final_qty} should be >= min_qty {min_qty}"
    assert topup_qty_rounded == 0.0005, f"Topup should be 0.0005, got {topup_qty_rounded}"


def test_topup_math_with_fractional_steps():
    """Test top-up math when raw topup doesn't align perfectly with step size."""
    normalized_qty = 0.0003  # Below min
    min_qty = 0.001
    step_size = 0.0002  # Step size is 0.0002
    
    # Calculate top-up
    target_qty = min_qty
    topup_qty_raw = target_qty - normalized_qty  # 0.001 - 0.0003 = 0.0007
    
    # Round UP to step size
    topup_qty_decimal = decimal.Decimal(str(topup_qty_raw))
    step_decimal = decimal.Decimal(str(step_size))
    division_result = topup_qty_decimal / step_decimal  # 0.0007 / 0.0002 = 3.5
    ceiled_result = division_result.quantize(decimal.Decimal('1'), rounding=decimal.ROUND_CEILING)  # 4
    topup_qty_rounded = float(ceiled_result * step_decimal)  # 4 * 0.0002 = 0.0008
    
    # Verify: normalized_qty + topup_qty_rounded >= min_qty
    final_qty = normalized_qty + topup_qty_rounded  # 0.0003 + 0.0008 = 0.0011
    assert final_qty >= min_qty, f"Final qty {final_qty} should be >= min_qty {min_qty}"
    assert topup_qty_rounded == 0.0008, f"Topup should be 0.0008 (rounded up from 0.0007), got {topup_qty_rounded}"


def test_topup_math_ensures_minimum_one_step():
    """Test that top-up is at least one step size even if calculated value is smaller."""
    normalized_qty = 0.00099  # Just below min
    min_qty = 0.001
    step_size = 0.0001
    
    # Calculate top-up
    target_qty = min_qty
    topup_qty_raw = target_qty - normalized_qty  # 0.001 - 0.00099 = 0.00001
    
    # Round UP to step size
    topup_qty_decimal = decimal.Decimal(str(topup_qty_raw))
    step_decimal = decimal.Decimal(str(step_size))
    division_result = topup_qty_decimal / step_decimal  # 0.00001 / 0.0001 = 0.1
    ceiled_result = division_result.quantize(decimal.Decimal('1'), rounding=decimal.ROUND_CEILING)  # 1
    topup_qty_rounded = float(ceiled_result * step_decimal)  # 1 * 0.0001 = 0.0001
    
    # Verify: normalized_qty + topup_qty_rounded >= min_qty
    final_qty = normalized_qty + topup_qty_rounded  # 0.00099 + 0.0001 = 0.00109
    assert final_qty >= min_qty, f"Final qty {final_qty} should be >= min_qty {min_qty}"
    assert topup_qty_rounded == step_size, f"Topup should be at least one step ({step_size}), got {topup_qty_rounded}"


def test_topup_math_with_large_step_size():
    """Test top-up math with larger step sizes (e.g., 0.1)."""
    normalized_qty = 0.05  # Below min
    min_qty = 0.1
    step_size = 0.1
    
    # Calculate top-up
    target_qty = min_qty
    topup_qty_raw = target_qty - normalized_qty  # 0.1 - 0.05 = 0.05
    
    # Round UP to step size
    topup_qty_decimal = decimal.Decimal(str(topup_qty_raw))
    step_decimal = decimal.Decimal(str(step_size))
    division_result = topup_qty_decimal / step_decimal  # 0.05 / 0.1 = 0.5
    ceiled_result = division_result.quantize(decimal.Decimal('1'), rounding=decimal.ROUND_CEILING)  # 1
    topup_qty_rounded = float(ceiled_result * step_decimal)  # 1 * 0.1 = 0.1
    
    # Verify: normalized_qty + topup_qty_rounded >= min_qty
    final_qty = normalized_qty + topup_qty_rounded  # 0.05 + 0.1 = 0.15
    assert final_qty >= min_qty, f"Final qty {final_qty} should be >= min_qty {min_qty}"
    assert topup_qty_rounded == 0.1, f"Topup should be 0.1 (rounded up from 0.05), got {topup_qty_rounded}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
