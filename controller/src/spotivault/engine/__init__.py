"""The run engine: runs, their queue, and one item at a time (plan § Item states, § Run states).

- `states.py`: the item and run state machines as tables; outcomes and badges. Frozen.
- `types.py`: what the run engine and the item engine pass each other. Frozen.
- `item.py`, `planning.py`, `steering.py`: one item from planning to outcome. Owner: engine-item.
- `run.py`, `queue.py`, `precheck.py`, `recovery.py`: the run, its queue, the pre-run check,
  start-up recovery, and `services.runs`. Owner: engine-run.

controller/ARCHITECTURE.md § S6's parts has the full split.
"""
