You are working inside my project automated-trading-platform.



Goal

When I toggle a trade/alert status (YES <-> NO) in the dashboard, the throttle counters for that item must reset. After switching to YES, the next evaluation must be allowed to notify immediately (bypass time/percentage throttles once), then normal throttling resumes.



Context

We already have throttling based on:

	•	minimum time since last alert/order

	•	minimum % price change since last alert/order

This works, but it does not reset when I manually toggle status.



Required behavior

	1.	On toggle from NO -> YES:

	•	Reset "last alerted at" / "last executed at" (and any last price used for % threshold) for that symbol+side+strategy (whatever key you use).

	•	Mark a one-time flag like force_next_signal=true so the next evaluation can send one message immediately even if thresholds would block it.

	•	After that one message is sent (or after the first evaluation pass, choose the safer option), clear force_next_signal.

	2.	On toggle from YES -> NO:

	•	Reset the same counters so that if I later re-enable, it behaves fresh.

	•	Ensure no pending cooldown state remains.

	3.	This must apply consistently to:

	•	Telegram notifications

	•	auto order placement (if enabled)

	•	the Monitoring tab "sent vs blocked" logging should reflect that the post-toggle message was "allowed due to reset/force"



Implementation constraints

	•	Do not rewrite the whole system. Minimal targeted changes.

	•	Keep existing throttling logic intact for normal cases.

	•	Use the same keying scheme already used for throttling (symbol/side/strategy/timeframe etc).



What to change (high level)

A. Find where the toggle endpoint is handled (backend route like PUT /api/watchlist/.../buy-alert and /sell-alert or similar).

B. In the toggle handler, when state changes, call a new helper in the throttling module/service:

	•	reset_throttle_state(key) and set_force_next_signal(key, true) when enabling

	•	reset_throttle_state(key) when disabling

C. Update the throttling check to allow if force_next_signal is true:

	•	allow send/order

	•	annotate decision reason: FORCED_AFTER_TOGGLE_RESET

	•	immediately clear the flag after allowing

D. Persist this state the same way your throttle state is stored today (in-memory cache, DB, Redis, etc). Match existing patterns.



Acceptance tests

	•	Toggle NO->YES and immediately run evaluation: first alert should send even if the last alert was seconds ago or price hasn't moved 1%.

	•	Next evaluation without price move/time elapsed should be blocked normally.

	•	Toggle YES->NO then YES->YES again (or NO->YES) should again allow one immediate alert.

	•	Monitoring table should show "allowed" with reason "forced after toggle reset".



Deliverables

	•	Code changes (backend) with minimal diffs.

	•	Add/adjust unit tests for throttle logic (pytest) to cover:

	•	reset clears last_time/last_price

	•	force flag bypasses once then clears

	•	Run tests locally and fix any failures.


