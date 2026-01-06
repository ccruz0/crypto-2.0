# Mandatory Verification Methodology (OFFICIAL)

## ⚠️ CRITICAL: This methodology is MANDATORY

Every fix, refactor, or deployment **MUST** be verified using this methodology.
This methodology is **NOT optional**.

---

## Required Verification Components

Every verification must include **BOTH**:

1. ✅ **AWS Dashboard verification** (dashboard.hilovivo.com)
2. ✅ **Backend verification** (logs + endpoints)

**If one of the two is missing, the verification is INVALID.**

---

## 1) AWS Dashboard Verification (Mandatory)

### Dashboard URL
**https://dashboard.hilovivo.com**

### Verification Steps

For the feature being verified:

1. **Navigate to the exact tab or screen affected**
2. **Observe the real, live values shown in the UI**
3. **Verify:**
   - ✅ Data loads correctly
   - ✅ No infinite loading
   - ✅ No placeholders
   - ✅ No stale or inconsistent values
4. **If useful:**
   - Take screenshots
   - Note exact values (prices, quantities, totals, statuses)

**The dashboard is the source of truth for user-visible state.**

### Required Documentation

You **MUST** explicitly state:
- ✅ What you see in the dashboard
- ✅ Which values are present
- ✅ Whether they make sense

---

## 2) Backend Verification (Mandatory)

For the same feature:

1. **Identify the backend endpoint(s)** powering that dashboard view
2. **Check backend logs and/or responses:**
   - ✅ Confirm the request arrives
   - ✅ Confirm the response payload and shape
   - ✅ Confirm values match what is shown in the dashboard
3. **Verify:**
   - ✅ Correct status codes
   - ✅ No silent errors
   - ✅ No hanging requests
   - ✅ Response closes properly

### Required Documentation

You **MUST** explicitly confirm:
- ✅ Backend values
- ✅ Response shape
- ✅ Consistency with the dashboard

---

## 3) Consistency Check (Critical)

Compare:
- **Dashboard values**
- **Backend values**

Confirm they are:
- ✅ Consistent
- ✅ Correctly mapped
- ✅ Not outdated
- ✅ Not partially rendered

**If there is any mismatch:**
- Identify the exact cause
- Apply the minimal fix
- Redeploy
- Re-verify using the SAME methodology

---

## 4) Verification Report Template (Required)

For every deploy or fix, produce:

### AWS Dashboard Check

- **URL**: https://dashboard.hilovivo.com
- **Section / Tab verified**: [Specify]
- **What values are visible**: [List exact values]
- **Screenshots taken**: YES / NO
- **Result**: PASS / FAIL

### Backend Check

- **Endpoint(s)**: [List endpoints]
- **Status codes**: [List status codes]
- **Key response fields**: [List fields]
- **Logs checked**: YES / NO
- **Result**: PASS / FAIL

### Consistency

- **Dashboard vs backend**: [Compare values]
- **Result**: CONSISTENT / INCONSISTENT

---

## 5) Final Verdict (Required)

Only after **both checks pass**:

- ✅ **SAFE TO SHIP**
  or
- ❌ **BLOCKED** (with reason)

**No partial approvals.**

---

## Enforcement Rule

From now on, any:
- Deployment
- Bug fix
- Refactor
- Data correction

**MUST** follow this methodology.

If a verification does not include:
- Inspection of **dashboard.hilovivo.com**
- Comparison with backend data

it is considered **INCOMPLETE**.




