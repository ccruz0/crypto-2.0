# LAB bootstrap evidence — atp-lab-openclaw

**Date:** YYYY-MM-DD  
**Region:** ap-southeast-1  
**VPC:** vpc-09930b85e52722581  
**Subnet:** subnet-055b8b41048d648aa (ap-southeast-1c)  
**Instance name:** atp-lab-openclaw  
**Instance ID:** _(fill after launch, e.g. i-xxxxxxxxx)_

---

## 1. Security group: atp-lab-sg

**Screenshot:** Inbound (empty) and Outbound rules.

_(Paste or attach screenshot: EC2 → Security Groups → atp-lab-sg.)_

- Inbound: none (SSM only).
- Outbound: HTTPS 443 → 0.0.0.0/0; HTTP 80 → 0.0.0.0/0; HTTP 80 → 169.254.169.254/32; Custom TCP 53 → 0.0.0.0/0; Custom UDP 53 → 0.0.0.0/0.

---

## 2. IAM role: atp-lab-ssm-role

**Screenshot:** Permissions tab showing attached policy.

_(Paste or attach screenshot: IAM → Roles → atp-lab-ssm-role → Permissions.)_

- Attached policy: **AmazonSSMManagedInstanceCore** only.

---

## 3. Instance summary

**Screenshot:** EC2 instance details (Name, Instance ID, State, VPC, Subnet, Security group, IAM role).

_(Paste or attach screenshot: EC2 → Instances → atp-lab-openclaw selected → Details.)_

- Name: atp-lab-openclaw  
- Subnet: subnet-055b8b41048d648aa (ap-southeast-1c)  
- Security group: atp-lab-sg  
- IAM role: atp-lab-ssm-role  
- Key pair: None  

---

## 4. Session Manager session

**Screenshot:** Session Manager browser tab with terminal open to atp-lab-openclaw.

_(Paste or attach screenshot: EC2 → Connect → Session Manager → Connect.)_

---

## 5. SSM status

**Screenshot or note:** Session Manager shows **Online** for atp-lab-openclaw.

_(Paste or attach screenshot: EC2 → Instances → atp-lab-openclaw → Details → Session Manager line, or Connect panel.)_

---

## 6. Validation command outputs (from Session Manager)

Run these in the Session Manager terminal and paste the full output below.

### uname -a

```
_(paste output here)_
```

### whoami

```
_(paste output here)_
```

### curl -sI https://api.telegram.org | head

```
_(paste output here)_
```

### getent hosts api.telegram.org

```
_(paste output here)_
```

### curl -s https://api.ipify.org ; echo

```
_(paste output here)_
```

---

## 7. Sign-off

- [ ] All screenshots above captured.
- [ ] All five validation commands run and outputs pasted.
- [ ] SSM remained Online during validation.

**Completed by:** _________________ **Date:** _________________
