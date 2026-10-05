# Actuator response monitoring

Passive heuristics, not calibrated diagnosis. The controller records successful
automatic ON commands and evaluates only newly saved sensor samples. Relay
state is a command/software state, not proof of physical operation. No relay
durations, setpoints, safety limits or control decisions are changed.

- Humidity and high-CO2 ventilation: at least 600 seconds, two ON commands,
  and three subsequent samples. Median of the last three samples compared with
  the pre-command measurement: +2 humidity percentage points or -50 ppm CO2,
  or reaching the control threshold, is considered a sufficient response.
- Light: continuously observed ON for 180 seconds, at least three samples,
  median below 5 lux raises suspicion. External light can hide a lamp failure.
- These constants are initial engineering heuristics and need actual grow-box
  measurements for calibration. No biological target is introduced.
- Stopped/colonization resets monitoring; simulation alerts are suppressed.
  Gaps beyond max(180 seconds, three sampling intervals), invalid values, or
  changed targets discard comparisons rather than extrapolate stale data.
- Routine ventilation already below the CO2 threshold is not evaluated.
  Camera-active samples are excluded from lighting assessment.
- Alerts feed the existing notification rules and per-device push delay/retry
  mechanism, and appear in the existing notification panel/history.
  A closed check is not proof that hardware was repaired.
- Assessment windows are intentionally in memory; restart needs fresh evidence.
  Existing push alert state/history stays persistent. Sparse/manual interventions
  and sensor flatlining are not independently diagnosed in this version.

Tests: `python -m unittest discover -s tests -p test_response_monitor.py -v`.
Physical response has not been calibrated or tested by switching live equipment
while the grow system is stopped.
