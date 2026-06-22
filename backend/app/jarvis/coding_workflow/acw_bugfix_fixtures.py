"""ACW v2 bugfix validation fixtures — concrete objectives for LAB validation."""

from __future__ import annotations

ACW_BF_001_OBJECTIVE = """\
Make ONE precise JSX text edit in frontend/src/app/page.tsx only.

File: frontend/src/app/page.tsx
Location: DashboardPageContent header (search for the h1 near "Configure Strategy", ~line 4644)

Replace this EXACT JSX line:
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Trading Dashboard</h1>

With this EXACT JSX line:
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Crypto Trading Dashboard</h1>

Acceptance criteria:
- Diff modifies frontend/src/app/page.tsx with a real JSX/TSX code change (not comment-only).
- The visible page title string changes from "Trading Dashboard" to "Crypto Trading Dashboard".
- className and element structure stay identical; only the inner text changes.
- Do not edit any other files, trading logic, secrets, or deploy scripts.
- Do not add TODO comments, placeholder comments, or explanatory comments instead of the JSX edit.
"""
