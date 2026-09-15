# MatLabGYM

MatLabGYM is a reproducible environment for evaluating scientific agents on materials-research decisions. The project is intentionally built as a greenfield scaffold: the public repository was empty at project start, so this first release establishes the contracts, a deterministic demo oracle, an auditable trace format, and tests before adding model training or real-lab connectivity.

## What this first release proves

The demo separates two capabilities that should not be conflated:

1. **Planning layer**: can an agent execute a long workflow while respecting state preconditions and resource limits?
2. **Decision layer**: after an experiment reveals evidence, can an agent choose the next candidate under a finite budget?

The built-in electrolyte oracle is an analytic fixture for smoke tests only. It is not a real conductivity model and must not be used as a scientific result. The production path is a versioned replay table or a validated physics/real-lab adapter implementing the same `OutcomeOracle` protocol.

## Quick start

```bash
cd MatLabGYM
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m matlabgym.demo --seed 7
python -m unittest discover -s tests -v
```

No API key, GPU, database, or external service is required for the smoke test.

## Architecture

```text
TaskSpec
  -> agent Action
  -> schema / precondition validator
  -> state transition engine
  -> OutcomeOracle (replay | physics | hybrid | real lab)
  -> Observation + task reward
  -> JSON-serialisable trace and evaluator
```

The scientific outcome is kept separate from reward. This lets us report `best_found`, `simple_regret`, `experiments_to_target`, validity, cost, and reproducibility without pretending that a hand-written scalar reward is ground truth.

## Current contracts

- `TaskSpec`: task id, goal, budget, maximum steps, target and version.
- `Action`: name plus JSON-compatible parameters.
- `Observation`: public state and available action catalogue.
- `StepResult`: observation, reward, termination flags, and structured info.
- `OutcomeOracle`: `measure(candidate, condition)` and `candidates()`.
- `trace()`: before-state, action, after-state, endpoint, failure reason, outcome, and reward.

The decision demo implements a discrete experimental replay environment. Results are hidden until the agent selects a candidate. Repeating a measurement is rejected and does not consume budget. The planning demo implements a five-stage cell workflow and rejects `cycle` before `formation`, demonstrating that success is based on executable state transitions rather than exact matching a single reference plan.

## Data and adapter path

To connect audited historical data, use `CSVReplayOracle.from_csv()` with:

```text
formulation_id,temperature_c,conductivity_ms_cm,uncertainty_ms_cm,source
E01,30,10.4,0.2,lab-run-2026-01
```

Only rows present in the replay table are queryable. If a condition was never measured, the environment must return an explicit missing-outcome error; it must not invent a value. A future `PyCalphadOracle`, `PyBaMMOracle`, or `RealLabAdapter` should preserve the same boundary and record database/model version, calibration range, runtime, and provenance.

## Evaluation protocol proposed for the next release

- Freeze train/dev/test task manifests and hidden seeds.
- Run random, greedy, Bayesian-optimization, and scripted baselines before RL.
- Report mean and standard deviation over pre-registered seeds.
- Separate `plan`, `dispatch`, `start`, and `completed` endpoints; dispatch is not execution.
- Add perturbation tracks for missing observations, delayed results, tool failures, unit changes, and invalid actions.
- Never expose the evaluator, hidden outcomes, or test-task generator to an evolving proposer.

The detailed, section-by-section revision plan is in [`docs/proposal_revision.md`](docs/proposal_revision.md). It maps the main proposal and all three supplied subdocuments to an implementable M0-M4 roadmap, including the evidence boundaries for replay, physics, hybrid, and real-lab backends.

## Scientific scope and limitations

This repository currently contains no real laboratory integration, no calibrated electrolyte dataset, no PyCalphad database, no PyBaMM parameter set, and no trained agent. The fixture is an engineering demonstration of the contract and replay mechanics. It is deliberately safe to run locally and should be replaced by audited data before any scientific claim.

## References

- Guo et al., *Stress-testing large language model agents in a robotic chemistry laboratory*, arXiv:2607.23045, 2026. https://arxiv.org/abs/2607.23045
- Wang et al., *ScienceWorld: Is your Agent Smarter than a 5th Grader?*, EMNLP 2022. https://aclanthology.org/2022.emnlp-main.775/
- Beeler et al., *ChemGymRL: A customizable interactive framework for reinforcement learning for digital chemistry*, Digital Discovery 2024. https://doi.org/10.1039/d3dd00183k
- Jansen et al., *DISCOVERYWORLD*, NeurIPS Datasets and Benchmarks 2024. https://arxiv.org/abs/2406.06769
- Cerrato et al., *Science-Gym: a simple testbed for AI-driven scientific discovery*, Machine Learning 2026. https://doi.org/10.1007/s10994-025-06914-x
- Dave et al., *Autonomous optimization of non-aqueous Li-ion battery electrolytes via robotic experimentation and machine learning coupling*, Nature Communications 2022. https://doi.org/10.1038/s41467-022-32938-1
