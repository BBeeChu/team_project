# The paper

**Collaborative AI agents for autonomous experimental research with solid-state quantum spins**, by El Mustapha Mansouri, Eikichi Kimura, Masato Koga and Keigo Arai, reports an autonomous investigation of ensembles of nitrogen-vacancy (NV) centres in diamond: quantum spins in a solid. The agents generated and rejected research questions, required separate theoretical checks and ran experiments designed to challenge their claims. An AI experimentalist operated an NV-diamond microscope.

## Research question and calibration law

The agents asked how many calibration settings were needed to predict the ensemble's response to a defined family of microwave pulse sequences. Here, $L$ is the maximum number of pulses in a sequence.

They derived an exact law: **when each spin's pulse errors persist through a sequence**, $L^2 + 1$ calibration measurements are necessary and sufficient to predict the ensemble's response to every sequence of up to $L$ phase-controlled pulses.

The computational researcher checked the law on a supercomputer. The laboratory investigation then tested its predictions on the NV ensemble.

## Search history

Over about 30 hours, the principal-investigator (PI) agent rejected 75 proposals and accepted none during the first 17 batches. Fresh proposals are newly generated proposals; revisions rework an earlier proposal.

The manager identified recurring rejected idea families, which accounted for 52 of the 56 earlier fresh proposals, and excluded them from the search. After that exclusion, nine new proposals explored seven previously unrepresented directions.

## Experimental redesign and signal drift

The PI rejected the initial experimental design because it could not separate the calibration law from simple interpolation. The manager proposed redesigning the experiment, and the PI developed a test that could distinguish the two.

The first experiment agreed with the predictions, but repeated reference measurements showed that the signal drifted during data collection. The agents treated the result as inconclusive and revised the measurement protocol without relaxing the acceptance criteria. The revised experiment met those criteria and supported the predictions.

## Human contributions

Humans assembled the apparatus, described its capabilities and configured the safety agent with preset operating limits, including maximum voltage and power.

## The study and the release

The study ran on earlier tooling. Auctopus implements the same roles, stages and decision checkpoints through the OpenAI and Anthropic APIs, with computational and laboratory agents reached over SSH.

The release contains the engine and templates; it does not include the study's prompts or NV instrument description. Users author their study instructions and domain pack using [Prompts](prompts.md) and [Domain packs](domain-packs.md). The repository's commands do not reproduce the paper.

See [Workflow](workflow.md) for the released engine's stages and decisions, and [Running](running.md#read-exit-codes-and-completion-markers) for exit codes.

## Citation

Citation metadata is supplied in [CITATION.cff](../CITATION.cff).

```bibtex
@misc{mansouri2026collaborative,
  title = {Collaborative AI agents for autonomous experimental research with solid-state quantum spins},
  author = {Mansouri, El Mustapha and Kimura, Eikichi and Koga, Masato and Arai, Keigo},
  year = {2026},
  note = {arXiv preprint}
}
```
