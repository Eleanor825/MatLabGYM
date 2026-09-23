# MatLabGYM Framework Architecture

## Scope

This framework turns a laboratory capability inventory into a verifiable agent environment. The first domain implements the six-stage electrolyte line from the interface template. It is an execution simulator, not a materials-performance oracle.

The [six-stage Operation Inventory](electrolyte_operation_inventory.md) records
current contracts and pending platform decisions. The
[Interface Acceptance Checklist](electrolyte_interface_acceptance.md) separates
existing simulator regression coverage from required physical-platform evidence.

## Paper-to-framework mapping

The χDL paper separates a portable procedure from a platform graph and compilation/execution. MatLabGYM preserves that architectural boundary and adds an episode layer:

| χDL concept | MatLabGYM concept | Purpose |
| --- | --- | --- |
| Hardware-independent procedure | `ProtocolSpec` | Portable sequence of typed operations. |
| Hardware graph | `ResourceSpec[]` | Available workstations and capacities. |
| Step declaration | `OperationSpec` | Parameters, units, I/O types and constraints. |
| Blueprint/high-level step | `SkillSpec` | Reusable atomic multi-operation protocol. |
| Compilation | `ProtocolCompiler` | Validate chains and bind concrete resources. |
| Platform executor | `LabRuntime` | Async jobs, logical time, locking and artifacts. |
| Execution trace | runtime events + env trace | Audit evidence for the deterministic replay verifier. |
| Not defined by χDL | `LabGymEnv` | Episode isolation, reward and termination. |

The official χDL code is not embedded because it is AGPL-3.0 and targets chemical synthesis hardware. An adapter can be added later behind the compiler/runtime boundary.

## Contracts

### Operation

Every platform operation declares:

```text
operation_id and version
owner and provenance
typed parameters, units and bounds
input artifact kind and state
output artifact kind and state
required resource type
duration and cost
interruptibility
```

The current domain treats `mix_electrolyte`, `characterize_electrolyte`, `inject_and_first_seal`, `formation_and_capacity`, `second_fill_and_degas`, and `test_cell_batch` as separate tools.

### Skill

A skill is an ordered list of operations plus defaults. `run_electrolyte_cell_line` is atomic: the Agent can start it and inspect its final provenance, but cannot stop or alter intermediate stages. This directly implements the template's distinction between a single-step tool and a combined multi-step skill.

### Artifact

Every completed operation produces an episode-scoped artifact:

```json
{
  "artifact_id": "ep-7-0001-characterized-electrolyte-0002",
  "artifact_kind": "characterized_electrolyte",
  "state": "characterized",
  "episode_id": "ep-7-0001",
  "producer_job_id": "ep-7-0001-job-0001",
  "parent_ids": ["ep-7-0001-electrolyte-batch-0001"],
  "metadata": {}
}
```

An artifact from an earlier reset is absent from the new workspace and cannot satisfy a precondition.

### Operation result

All commands return the same shape:

```json
{
  "success": true,
  "status": "accepted",
  "request_id": "mix-001",
  "job_id": "ep-7-0001-job-0001",
  "produced_artifact_ids": [],
  "estimated_completion_min": 30.0,
  "incremental_cost": 12.0,
  "total_cost": 12.0,
  "failure_code": null,
  "failure_reason": null,
  "retryable": false,
  "replayed": false
}
```

This supplies simulated job/artifact IDs, logical ETA, configured total cost,
success and failure reason, with stable error codes and retry semantics.
Mapping these IDs to physical laboratory entities and verifying time/cost sources
remain platform-integration work. An accepted job has no completed output artifact yet.

## State machine

The electrolyte domain enforces this artifact chain:

```text
recipe
  -> electrolyte_batch:mixed
  -> characterized_electrolyte:characterized
  -> first_sealed_cell_batch:first_sealed
  -> formed_cell_batch:formed
  -> degassed_cell_batch:degassed
  -> cell_test_report:completed
```

Inputs are checked at compile time and validated again when a compiled plan is submitted. The compiled plan carries its source protocol and hash; runtime validation binds both before dispatch. Resource capacity is checked at dispatch time, and equivalent devices are selected by current load. Jobs reserve resources and physical inputs until they complete or are stopped; a consumable input cannot be used twice within one plan or across jobs. Logical time is advanced explicitly. Fresh environments with the same manifest, seed, and action sequence have deterministic dynamics and traces; repeated resets on one instance use distinct episode namespaces.

The environment caps time advancement at the task deadline and rejects negative, boolean, non-finite, oversized, and string time values. Compiled plans must match the frozen registry and platform hashes, source protocol, registered costs and durations, input chain, parameter constraints, resource types, and interruptibility. Nested parameters, observations, and exported traces are isolated so caller mutation cannot change accepted work or provenance. All mutating runtime commands are idempotent by request ID.

## Reward

`RewardSpec` is benchmark configuration, not environment truth. It can score accepted jobs, completed operations, invalid actions, stopping, goal completion, cost, and elapsed logical time. A different reward version produces a different manifest hash.

This supports Agent evolution within a chosen Gym while preserving reproducibility:

```text
fixed environment dynamics + fixed reward version
  -> evolve policy / planner / Skill / harness
  -> evaluate on frozen manifests and seeds
```

Environment and reward evolution are outer-loop changes and must create new versioned manifests.

### Benchmark admission boundary

`matlabgym.benchmark` contains the paper-facing contracts for an `OracleCard`,
grouped dataset split, registered perturbation suite, endpoint evidence and a
composite `BenchmarkManifest`. These are intentionally fail-closed. A manifest
cannot be admitted as a scientific benchmark unless the oracle is marked
validated, the split hashes match, every perturbation operator is implemented,
and the claim status is explicitly `scientific_benchmark`.

The bundled electrolyte line does not satisfy that gate. Its default manifest
uses `unregistered` oracle/split/stress hashes and `execution_only` semantics.
This is correct for a contract scaffold and prevents an execution demo from
being reported as a materials result.

## Extension pipeline

1. Inventory real operations, start/stop support, resources, capacities, units, costs, and failure codes.
2. Register `OperationSpec` objects with a business owner and source provenance.
3. Register reusable `SkillSpec` objects and define whether intermediate control is allowed.
4. Add resources and capacities as the platform graph.
5. Compile known successful protocols and verify that invalid chains fail.
6. Replay historical execution logs against artifact lineage and job status transitions.
7. Add a real scheduler adapter preserving `OperationResult` and endpoint semantics.
8. Add a scientific outcome oracle only after execution semantics pass their validation gate.
9. Freeze task, registry, platform, and reward in a manifest; version the evaluator and seed set alongside it.
10. Run baselines and evolving agents against the same frozen manifest and evaluation configuration.

## Current limitations

- A `recipe` is currently validated as a JSON object; production use needs a dedicated composition/unit schema.
- The reference runtime reserves every resource needed by an atomic skill for the skill's entire duration. A production scheduler should support per-step reservations while keeping agent control atomic.
- Stop currently has `stopped` semantics without resume or partial-product recovery.
- Durations and costs are configured proxy values. They are not observed laboratory measurements.
- Hidden evaluators require process/storage isolation in a formal benchmark deployment.
- `matlabgym.replay.verify_trace` verifies deterministic traces by comparing
  manifest, before/after snapshots, result payloads, endpoint evidence, rewards,
  terminal flags and state hashes. It is not a stochastic replay engine and it
  does not prove physical start or scientific validity.
- `matlabgym.runner` provides fixed-slot execution-only cohort runs and retains
  unscorable/runner-failed slots as zero-score denominator entries. `matlabgym.stress`
  provides explicitly synthetic paired invalid-action, duplicate-action and
  time-delay operators with pair-level delta summaries. Real failure replay,
  hidden holdouts, scientific evaluators and adversarial sandboxing remain future
  work.
