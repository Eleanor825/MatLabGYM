# Literature Traceability and Paper-Readiness Audit

This document records what the cited work actually establishes, which MatLabGYM
contract it motivates, and what the current repository does or does not prove.
The audit uses primary papers and official repositories only. It is a design and
readiness record, not a claim that MatLabGYM reproduces any cited benchmark.

## Primary Anchors

| Work | Verified contribution | MatLabGYM requirement | Current status |
| --- | --- | --- | --- |
| Guo et al., [Stress-testing large language model agents in a robotic chemistry laboratory](https://arxiv.org/abs/2607.23045), official [LabBench](https://github.com/pic-ai-robotic-chemistry/LabBench) at `d4d5059cfa38e373ea49461cf27254e29dd40edc` | 45 workstations, 62 operations, 433 constraints, 456 parameter fields; 32 locked tasks; 48 observed harness-model configurations; 4,608 trials; 3.3% fixed-denominator expert-assessed executable workflows and 28.1% for the best configuration. N1-N10 separate planning, review, dispatch and expert executability. N10 is explicitly not started/completed evidence. | Fixed-denominator trial slots, authority endpoint records, task-ID dispatch evidence, expert executable adjudication, long-horizon operation statistics, and workflow-level replanning metrics. | Contract scaffolding only. The repo has no LabBench task corpus, N1-N10 normalization, expert labels, harness matrix, or physical telemetry. |
| Rauschen et al., [χDL](https://doi.org/10.1038/s44160-023-00473-6), official [Cronin XDL](https://gitlab.com/croningroup/chemputer/xdl) | Portable procedure representation separated from platform graph, compilation and execution. | Keep protocol, platform resources, compiler, runtime and episode layer separate; validate portability with adapters before claiming it. | Architectural inspiration and compiler/runtime boundary. No cross-platform conformance experiment is included. |
| Beeler et al., [ChemGymRL](https://doi.org/10.1039/d3dd00183k), official [repository](https://github.com/chemgymrl/chemgymrl) | Modular chemistry benches, vessels, event/state transitions and Gymnasium-compatible RL interfaces. | Typed vessel/sample transfer, units, conservation, safety and explicit process/terminal rewards. | Execution contracts exist; chemistry dynamics are not calibrated and are not scientific ground truth. |
| Cerrato et al., [Science-Gym](https://doi.org/10.1007/s10994-025-06914-x), official [repository](https://github.com/Pibborn/Science-gym) | Seven Gym-compatible scientific simulations with distinct collection, observation, reward and equation-discovery interfaces. | Separate data collection, scientific objective and discovery/equation evaluation; do not conflate equation recovery with materials validity. | Not implemented. |
| Polat et al., [STEMGym](https://arxiv.org/abs/2606.29592), official [repository](https://github.com/KurbanIntelligenceLab/STEMGym) | 15 physics-simulated STEM worlds, hard irreversible dose budgets and DEC-AUC information-cost curves; analyst and navigator are evaluated separately. | Hard sample/time/resource budgets, anytime information-cost curves and decoupled perception/planning components. | Not implemented. |
| Gandhi et al., [BoxingGym](https://arxiv.org/abs/2501.01540), official [repository](https://github.com/kanishkg/boxing-gym) | Ten generative probabilistic environments with exact generative models, EIG and model-discovery evaluation. | EIG is permitted only for an explicit generative model with likelihood/posterior; historical replay reports regret and sample efficiency instead. | Replay boundary is documented; no generative oracle is included. |
| Gu et al., [BLADE](https://arxiv.org/abs/2408.09667), official [repository](https://github.com/behavioral-data/BLADE) | Multiple valid data analyses matched to expert decisions with precision/coverage metrics and execution errors counted. | Multi-path/facet evaluator instead of exact-match or a single LLM judge. | No data-analysis evaluator yet. |
| Chen et al., [ScienceAgentBench](https://arxiv.org/abs/2410.05080), official [repository](https://github.com/OSU-NLP-Group/ScienceAgentBench) | 102 executable tasks from 44 papers, expert validation, standalone program artifacts, execution/scientific/cost metrics and contamination controls. | Artifact-first evaluation, execution validity separate from scientific outcome, cost and split provenance. | Manifest and trace contracts exist; no scientific task corpus or runner. |
| Shen et al., [SciAgentGym](https://arxiv.org/abs/2602.12984), official [repository](https://github.com/CMarsRover/SciAgentGYM) | Typed multi-step scientific tools, isolated filesystem/database/Python execution, fixed-seed structured traces, recovery and path-efficiency metrics. | Typed tool protocol, immutable traces, isolated workspace and recovery/loop metrics. | In-memory deterministic runtime only; no process/network sandbox. |
| Jansen et al., [DISCOVERYWORLD](https://arxiv.org/abs/2406.06769), official [repository](https://github.com/allenai/discoveryworld) | Parametric hidden worlds, hypothesis-to-experiment-to-conclusion tasks, process metrics and explanatory-knowledge metrics. | Hidden task variants, partial process scoring and long-horizon replanning. | No discovery-world task generator. |
| Debenedetti et al., [AgentDojo](https://arxiv.org/abs/2406.13352), official [repository](https://github.com/ethz-spylab/agentdojo) | Stateful tools with untrusted observations, attacker-goal cross-products and separate benign utility/security metrics. | Treat notebooks, comments, files and tool returns as untrusted; report utility, utility-under-attack, attack success and scientific success separately. | No adversarial sandbox or attack executor yet. |

## Stress-Test Boundary

The robotic-chemistry paper is the most important methodological reference, but
its numbers must be interpreted exactly:

1. N1-N8 are node-level assessments with fixed denominators and are not a
   monotonic funnel.
2. N9 is authoritative verified dispatch evidence tied to a task identifier and
   trial slot.
3. N10 is a separate expert label of workflow executability. It is not proof
   that a physical task started or completed.
4. The reported 3.3% and 28.1% are executable-workflow rates, not material
   discovery success, scientific validity, or deployment readiness.

MatLabGYM therefore labels the deterministic runtime's accepted plan as
`dispatch_verified` only within the simulator. It explicitly emits
`started=false` and `scientifically_validated=false`. This is intentionally more
conservative than calling a logical completion a physical experiment.

## Current Readiness Verdict

The repository is an **execution-only benchmark substrate**. It currently has:

- typed operation, skill, protocol and artifact contracts;
- compiler/runtime validation and sample/resource locking;
- manifest hashes and source-protocol attestation;
- deterministic transition traces and a full deterministic replay verifier;
- fail-closed `OracleCard`, split, perturbation and benchmark-manifest contracts;
- explicit measured-support handling for sparse CSV replay and replicate rows;
- endpoint evidence with an honest physical-start/scientific-validation boundary;
- deterministic score summaries and 45 regression tests.

It does **not** yet have:

- a 45-workstation/32-task LabBench-compatible corpus;
- model x harness trial matrix, slot replacement and fixed-denominator cohort runner;
- actual perturbation operators or prompt-injection sandbox;
- calibrated electrolyte, CALPHAD or PyBaMM scientific oracle;
- expert N10 adjudication, R1-R6 scoring, judge agreement or task-cluster bootstrap;
- real dispatch/start/completion telemetry or sim-to-real evidence;
- a benchmark claim admission artifact with validated oracle, implemented stress
  suite and frozen train/dev/test data.

The correct paper positioning at this revision is therefore: **a verifiable
execution and evaluation substrate for a future materials-agent benchmark**, not
an established materials-discovery benchmark and not a reproduction of LabBench.

## Required Next Gates

1. Freeze and license a first real replay dataset; publish an OracleCard with a
   grouped split, support mask, replicate policy, uncertainty semantics and
   calibration report.
2. Implement paired perturbation operators and an attack sandbox, then require
   `BenchmarkManifest.assert_benchmark_ready` before reporting scientific scores.
3. Add a cohort runner with fixed trial slots, retained failures, per-task
   endpoint records, baseline policies (random, greedy, BO where valid) and
   task-cluster bootstrap confidence intervals.
4. Add an independent evaluator for scientific outcome, execution evidence,
   resource cost and security side effects. Keep all four axes separate.
5. Only after those gates, add AlloyEnv or CellEnv and run simulator-to-real
   calibration. Do not develop both new backends before one is validated.
