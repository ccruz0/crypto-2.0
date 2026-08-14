"""Explicit Telegram SL/TP create must override skip_sl_tp_reminder.

2026-08-13 ATP Control: position review offered Crear SL/TP for SUI_USD, but the
callback hit create_sl_tp_for_position without force → ERROR "reminder skipped".
"""

from unittest.mock import MagicMock, patch

from app.services.telegram_commands import (
    handle_create_sl_command,
    handle_create_sl_tp_command,
    handle_create_tp_command,
)


def test_create_sl_tp_command_passes_force_true():
    db = MagicMock()
    with patch(
        "app.services.sl_tp_checker.sl_tp_checker_service"
    ) as checker, patch(
        "app.services.telegram_commands.send_command_response", return_value=True
    ) as send:
        checker.create_sl_tp_for_position.return_value = {
            "success": True,
            "sl_order_id": "sl-1",
            "tp_order_id": "tp-1",
        }
        assert handle_create_sl_tp_command("chat", "/create_sl_tp SUI_USD", db) is True
        checker.create_sl_tp_for_position.assert_called_once_with(
            db, "SUI_USD", force=True
        )
        assert "SL/TP CREATED" in send.call_args[0][1]


def test_create_sl_command_passes_force_true():
    db = MagicMock()
    with patch(
        "app.services.sl_tp_checker.sl_tp_checker_service"
    ) as checker, patch(
        "app.services.telegram_commands.send_command_response", return_value=True
    ):
        checker.create_sl_for_position.return_value = {
            "success": True,
            "sl_order_id": "sl-1",
        }
        assert handle_create_sl_command("chat", "/create_sl SUI_USD", db) is True
        checker.create_sl_for_position.assert_called_once_with(
            db, "SUI_USD", force=True
        )


def test_create_tp_command_passes_force_true():
    db = MagicMock()
    with patch(
        "app.services.sl_tp_checker.sl_tp_checker_service"
    ) as checker, patch(
        "app.services.telegram_commands.send_command_response", return_value=True
    ):
        checker.create_tp_for_position.return_value = {
            "success": True,
            "tp_order_id": "tp-1",
        }
        assert handle_create_tp_command("chat", "/create_tp SUI_USD", db) is True
        checker.create_tp_for_position.assert_called_once_with(
            db, "SUI_USD", force=True
        )


def test_create_sl_tp_no_longer_surfaces_reminder_skip_as_error():
    """Regression: skip_reminder alone must not produce ERROR CREATING when force is used."""
    db = MagicMock()
    with patch(
        "app.services.sl_tp_checker.sl_tp_checker_service"
    ) as checker, patch(
        "app.services.telegram_commands.send_command_response", return_value=True
    ) as send:
        # Simulate pre-fix behavior returning the skip error — handler must still
        # have requested force=True so production won't take this path for skip alone.
        checker.create_sl_tp_for_position.return_value = {
            "success": False,
            "error": "SL/TP reminder skipped for SUI_USD (use force=True to override)",
        }
        handle_create_sl_tp_command("chat", "/create_sl_tp SUI_USD", db)
        kwargs = checker.create_sl_tp_for_position.call_args
        assert kwargs.kwargs.get("force") is True or (
            len(kwargs.args) >= 3 and kwargs.args[2] is True
        )
        # Error path still formats ERROR when create genuinely fails after force.
        assert "ERROR CREATING SL/TP" in send.call_args[0][1]
