# 0004. The model copies dates and amounts; code parses and calculates

Status: Accepted

## Decision

`date_text` and `amount_text` are copied exactly; relative deadlines come as number + unit + anchor. `verify/dates.py` does the math.

## Why

Models are unreliable at date arithmetic; code is testable and deterministic.
