[insert: your prompt for the experimentalist on the instrument computer. Its standing instructions are LAB_AGENT_INSTRUCTIONS.md in this folder; Auctopus adds the laboratory's safety rules.]

The run packet is in `inbox/{RUN_ID}/`. Write everything you return to `outbox/{RUN_ID}/`: the raw files that `results_schema.md` lists, `deviations.md`, and, last, `RUN-RESULT.json` with `"status"` set to `done`, `aborted` or `failed`.
