# AI Agent Usage Guidelines

## Purpose

This document defines mandatory rules and best practices for using AI agents in this repository to prevent excessive credit consumption and ensure efficient resource usage.

## Mandatory Rules

### 1. Maximum Concurrent Agents
- **Maximum 1 AI agent running in Auto mode at any time.**
- Multiple agents running in parallel multiply credit consumption non-linearly.
- Each agent consumes credits independently.

### 2. Auto Mode Restrictions
- **Auto mode must never be used for continuous or open-ended tasks.**
- Auto mode reprocesses context repeatedly, leading to exponential credit consumption.
- Use Auto mode only for tasks with a clear, bounded scope.

### 3. Task Definition Requirements
- **Agents must always have a single, well-defined objective.**
- Vague or multi-part objectives lead to excessive iterations and credit waste.
- Each task must have a clear completion criterion.

## When Auto Mode Is Allowed

Auto mode may be used only for the following scenarios:

1. **Bug fixes with a closed scope**
   - Specific bug identified and isolated
   - Fix path is clear
   - Testing criteria are defined

2. **Audits of a single module or file**
   - Single file or module to review
   - Specific audit criteria provided
   - Deliverable is a report or list of findings

3. **Generating a specific diff, patch, or prompt**
   - Exact output format specified
   - Input files clearly identified
   - Single iteration expected

4. **Short validation runs**
   - Quick verification of a specific change
   - Limited file scope
   - Binary pass/fail outcome

## Required Agent Configuration Before Running Auto

Before starting an agent in Auto mode, you must explicitly define:

1. **Explicit objective**
   - Single, clear statement of what the agent must accomplish
   - Measurable success criteria
   - Example: "Fix the authentication error in `backend/app/api/auth.py` that causes 401 responses"

2. **Explicit list of allowed files**
   - Specific files the agent may modify
   - No wildcards or "all files in directory" unless explicitly necessary
   - Example: `["backend/app/api/auth.py", "backend/app/core/config.py"]`

3. **Explicit stop condition**
   - Clear definition of when the task is complete
   - Maximum number of iterations if applicable
   - Example: "Stop when the authentication test passes and no linter errors remain"

4. **Change restrictions**
   - No refactors unless explicitly requested
   - No renames unless explicitly requested
   - No formatting-only changes unless explicitly requested
   - Only make changes necessary to achieve the stated objective

## Best Practices

### 1. Prefer Manual Mode for Exploration
- Use manual mode when exploring codebases or analyzing issues
- Manual mode allows controlled, step-by-step investigation
- Switch to Auto mode only after the problem and solution are well-understood

### 2. Split Large Tasks
- Break complex tasks into sequential, smaller steps
- Complete each step before starting the next
- Each step should be a separate agent session with its own objective

### 3. Immediate Agent Termination
- Stop and close agents immediately after task completion
- Do not leave agents running "just in case"
- Verify completion, then terminate the agent session

### 4. Monitor Credit Consumption
- Be aware of credit usage during agent sessions
- If consumption seems excessive, stop and reassess the approach
- Consider switching to manual mode if Auto mode is consuming too many credits

## Rationale

### Credit Consumption Model
- **Each agent consumes credits independently**: Running multiple agents multiplies costs
- **Auto mode reprocesses context repeatedly**: Each iteration re-reads files and re-processes context, leading to exponential consumption
- **Parallel agents multiply consumption non-linearly**: Two agents don't just double consumption; they may quadruple it due to context overlap

### Why These Rules Matter
- Uncontrolled agent usage can quickly exhaust available credits
- Auto mode is powerful but expensive; use it judiciously
- Clear boundaries prevent scope creep and unnecessary iterations
- Proper configuration ensures agents complete tasks efficiently without waste

## Enforcement

- Review agent usage regularly
- If credit consumption exceeds expectations, review these guidelines
- Adjust agent configuration based on actual usage patterns
- Document exceptions and their rationale if Auto mode is used outside these guidelines

---

**Last Updated**: 2025-01-27


