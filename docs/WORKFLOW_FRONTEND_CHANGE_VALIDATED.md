# ✅ Cursor Workflow AI – "Frontend Change (Validated e2e)"

**Workflow Name:** `Frontend Change (Validated e2e)`

**This is a Workflow AI Prompt for Cursor. Use this workflow for ANY frontend or behaviour change.**

---

## Workflow AI Prompt

This workflow enforces a fully autonomous, end-to-end validated development cycle for ANY frontend or behaviour change in the automated-trading-platform.

You MUST:

1. **Read the user's request.**

2. **Investigate the affected code (frontend + backend if needed).**

3. **Apply the change.**

4. **Test locally (Node, Next.js, lint, types).**

5. **Build locally.**

6. **Fix any errors automatically.**

7. **Deploy to AWS (backend if needed) and Vercel (frontend).**

8. **Launch the real production dashboard:**
   ```
   https://monitoring-ai-dashboard-nu.vercel.app/
   ```

9. **Validate the change visually and functionally:**
   - UI behaviour  
   - Presets  
   - RSI/MA/EMA  
   - Volume ratio  
   - Alerts behavior (NO real orders)  
   - Toggles persistency  
   - Watchlist/Signals consistency  
   - Market data accuracy  

10. **Check backend logs for errors.**

11. **Check browser console for errors.**

12. **If something is wrong → fix → rebuild → redeploy → retest.**

13. **Repeat autonomously until the behaviour is correct.**

14. **Only then produce a final confirmation + screenshots.**

---

## Mandatory Rules

- **NO questions to the user.**
- **NO real orders EVER.**
- **ALWAYS validate business logic against:**
  - `docs/monitoring/business_rules_canonical.md`
  - `docs/CURSOR_AUTONOMOUS_EXECUTION_GUIDELINES.md`
- **ALWAYS ensure the frontend and backend state match.**
- **ALWAYS validate the final result live in the browser.**
- **ALWAYS iterate until the change behaves perfectly.**

**This workflow must run autonomously and completely finish the full cycle every time it is invoked.**

---

## Quick Reference Commands

### Local Testing
```bash
cd /Users/carloscruz/automated-trading-platform/frontend
npm run lint
npm run build
npm run type-check  # if available
```

### Frontend Deployment (Vercel)
```bash
# Vercel deployment is typically automatic via git push
# Or manual: vercel --prod
```

### Backend Deployment (AWS)
```bash
sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose down'"
sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose up --build -d'"
```

### Health Check
```bash
curl -s https://monitoring-ai-dashboard-nu.vercel.app/api/health
```

### Backend Logs
```bash
cd /Users/carloscruz/automated-trading-platform && bash scripts/aws_backend_logs.sh --tail 200
```

### Dashboard URL
```
https://monitoring-ai-dashboard-nu.vercel.app/
```

---

## Workflow Execution Flow

```
User Request
    ↓
Investigate Code
    ↓
Apply Change
    ↓
Local Tests (lint, build, types)
    ↓
Fix Errors (if any)
    ↓
Deploy (AWS + Vercel)
    ↓
Open Live Dashboard
    ↓
Validate Visually & Functionally
    ↓
Check Logs (backend + browser console)
    ↓
[If Issues Found] → Fix → Rebuild → Redeploy → Retest
    ↓
[Repeat until perfect]
    ↓
Final Confirmation + Screenshots
```

---

## Validation Checklist

For every frontend change, validate:

- [ ] UI renders correctly
- [ ] No console errors
- [ ] No TypeScript errors
- [ ] Presets work correctly
- [ ] RSI/MA/EMA values display correctly
- [ ] Volume ratio matches backend
- [ ] Alerts toggle works (NO real orders)
- [ ] Toggles persist after refresh
- [ ] Watchlist data matches backend API
- [ ] Signals chip matches backend decision
- [ ] Market data is accurate
- [ ] Backend logs show no errors
- [ ] Business rules are followed

---

## Related Workflows

- **Watchlist Audit:** `docs/WORKFLOW_WATCHLIST_AUDIT.md` - Full Watchlist validation workflow
- **Autonomous Execution Guidelines:** `docs/CURSOR_AUTONOMOUS_EXECUTION_GUIDELINES.md` - General execution protocol

---

## Notes

- This workflow is designed for frontend changes that require full end-to-end validation
- Always test in the production environment (Vercel) after deployment
- Never create real orders during testing
- Always validate against business rules before marking as complete

