# Instrument specification: the DiscoveryWorld environment

## Current capabilities

Scenario {{SCENARIO}}, difficulty {{DIFFICULTY}}, parametric seed {{SEED}}. One experimentalist agent acts in a 2D top-down world of rooms, outdoor areas, objects, instruments and non-player characters. The run has an action budget of {{STEPS}} actions (each action is one environment step); the environment reports whether the task is complete.

Task given to the agent: {{TASK_DESCRIPTION}}

### Observation
At every step the agent receives: its location and facing direction; the objects directly in front of it or in its inventory (the only ones it can act on), each with a name, a description and a uuid; the objects within three tiles, grouped by direction; the message returned by the last action (instrument readings arrive here); any open dialog with its options; the latest Discovery Feed posts; the task description and whether it is complete. Images of the world are not used.

### Actions (JSON, one per step)
{{ACTIONS}}

- MOVE_DIRECTION and ROTATE_DIRECTION take "north", "east", "south" or "west". TELEPORT_TO_OBJECT takes an object's uuid and places the agent beside it, even if it is far away or unseen; TELEPORT_TO_LOCATION takes one of these names: {{TELEPORTS}}. USE takes the instrument's uuid as arg1 and the target's uuid as arg2; the reading comes back in the action message. In a dialog the agent answers with a chosen option number.
- The agent can act only on objects in its inventory or directly in front of it. Containers must be opened. Characters may hold information (TALK) and some tasks require entering a final answer into a device (USE or dialog).

### Initial observation (seed {{SEED}})
```json
{{INITIAL_OBSERVATION}}
```

### What comes back from a run
- `data/trajectory.jsonl`: one JSON object per step: step, observation (summary as above), action, success, errors, result_message, protocol_step, explanation, memory, running_hypotheses.
- `data/notes.md`: the experimentalist's final memory and hypotheses. `data/final_knowledge.md`: its final statement of what it learned. `data/environment.log`: the environment's own log.
- `deviations.md` and `RUN-RESULT.json` (status done, aborted or failed).

### Hard limits and what is not possible
- The action budget is {{STEPS}}; the run ends at the budget or when the environment reports the task complete.
- The scorecard, the critical questions and any oracle knowledge of the environment are never available to any agent; conclusions must rest on readings in the trajectory.
- No file outside `outbox/<run-id>/` is returned; no code runs inside the environment.
- The experimentalist is a model-driven agent that follows the protocol as far as the world allows; steps that name objects not present are skipped and recorded in deviations.md.
