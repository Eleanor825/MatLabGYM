import copy
import unittest
from dataclasses import replace

from matlabgym.core import Action
from matlabgym.domains.electrolyte_line import (
    build_electrolyte_line_env,
    build_electrolyte_registry,
    electrolyte_resources,
)
from matlabgym.lab import (
    Artifact,
    CompilationError,
    CompiledProtocol,
    CompiledStep,
    ConfigurableReward,
    LabGymEnv,
    LabRuntime,
    LabTaskSpec,
    OperationSpec,
    ParameterSpec,
    ProtocolCompiler,
    ProtocolSpec,
    ProtocolStep,
    ResourceSpec,
    RewardSpec,
    stable_hash,
)

RECIPE = {
    "components": [
        {"material": "EC", "fraction": 0.3},
        {"material": "EMC", "fraction": 0.7},
        {"material": "LiPF6", "concentration_m": 1.0},
    ]
}


def skill_action(request_id="skill-1"):
    return Action(
        "start_skill",
        {
            "skill_id": "run_electrolyte_cell_line",
            "request_id": request_id,
            "parameters_by_step": {
                "mix": {"recipe": RECIPE, "batch_size_ml": 20.0},
            },
        },
    )


class ElectrolyteLineTests(unittest.TestCase):
    def test_atomic_skill_reaches_goal(self):
        env = build_electrolyte_line_env()
        _, reset_info = env.reset(seed=11)
        accepted = env.step(skill_action())
        self.assertTrue(accepted.info["results"][0]["success"])
        self.assertEqual(accepted.info["results"][0]["status"], "accepted")

        completed = env.step(Action("advance_time", {"minutes": 905, "request_id": "advance-1"}))
        self.assertTrue(completed.terminated)
        self.assertFalse(completed.truncated)
        self.assertTrue(completed.observation.public_state["artifacts"])
        self.assertEqual(reset_info["manifest_hash"], completed.info["manifest_hash"])

    def test_atomic_skill_cannot_be_stopped(self):
        env = build_electrolyte_line_env()
        env.reset(seed=1)
        accepted = env.step(skill_action())
        job_id = accepted.info["results"][0]["job_id"]
        stopped = env.step(Action("stop_job", {"job_id": job_id, "request_id": "stop-1"}))
        result = stopped.info["results"][0]
        self.assertFalse(result["success"])
        self.assertEqual(result["failure_code"], "NOT_INTERRUPTIBLE")

    def test_tool_can_be_stopped_when_interruptible(self):
        env = build_electrolyte_line_env()
        env.reset(seed=2)
        accepted = env.step(
            Action(
                "start_operation",
                {
                    "operation_id": "mix_electrolyte",
                    "request_id": "mix-1",
                    "parameters": {"recipe": RECIPE, "batch_size_ml": 10.0},
                },
            )
        )
        job_id = accepted.info["results"][0]["job_id"]
        result = env.step(Action("stop_job", {"job_id": job_id, "request_id": "stop-2"}))
        self.assertEqual(result.info["results"][0]["status"], "stopped")

    def test_out_of_order_input_is_rejected(self):
        env = build_electrolyte_line_env()
        env.reset(seed=3)
        result = env.step(
            Action(
                "start_operation",
                {
                    "operation_id": "inject_and_first_seal",
                    "input_id": "not-produced",
                    "request_id": "bad-order",
                    "parameters": {"cell_count": 8},
                },
            )
        )
        self.assertFalse(result.info["results"][0]["success"])
        self.assertEqual(result.info["results"][0]["failure_code"], "INPUT_NOT_FOUND")

    def test_request_id_is_idempotent(self):
        env = build_electrolyte_line_env()
        env.reset(seed=4)
        first = env.step(skill_action("same-request"))
        second = env.step(skill_action("same-request"))
        first_result = first.info["results"][0]
        second_result = second.info["results"][0]
        self.assertEqual(first_result["job_id"], second_result["job_id"])
        self.assertEqual(second_result["incremental_cost"], 0.0)
        self.assertTrue(second_result["replayed"])
        self.assertEqual(second.reward, 0.0)
        self.assertEqual(first.info["total_cost"], second.info["total_cost"])

    def test_request_id_conflict_is_rejected(self):
        env = build_electrolyte_line_env()
        env.reset(seed=40)
        env.step(skill_action("conflict"))
        changed = skill_action("conflict")
        changed_payload = dict(changed.parameters)
        changed_payload["parameters_by_step"] = {"mix": {"recipe": RECIPE, "batch_size_ml": 30.0}}
        result = env.step(Action("start_skill", changed_payload))
        self.assertEqual(result.info["results"][0]["failure_code"], "REQUEST_CONFLICT")

    def test_resource_capacity_is_enforced(self):
        env = build_electrolyte_line_env()
        env.reset(seed=41)

        def action(request_id):
            return Action(
                "start_operation",
                {
                    "operation_id": "mix_electrolyte",
                    "request_id": request_id,
                    "parameters": {"recipe": RECIPE, "batch_size_ml": 10.0},
                },
            )

        self.assertTrue(env.step(action("mix-a")).info["results"][0]["success"])
        busy = env.step(action("mix-b"))
        self.assertEqual(busy.info["results"][0]["failure_code"], "RESOURCE_BUSY")
        self.assertTrue(busy.info["results"][0]["retryable"])

    def test_physical_artifact_cannot_be_used_by_two_jobs(self):
        env = build_electrolyte_line_env()
        env.reset(seed=44)
        accepted = env.step(
            Action(
                "start_operation",
                {
                    "operation_id": "mix_electrolyte",
                    "request_id": "make-batch",
                    "parameters": {"recipe": RECIPE, "batch_size_ml": 10.0},
                },
            )
        )
        env.step(Action("advance_time", {"minutes": 30, "request_id": "finish-batch"}))
        artifact_id = env.runtime.jobs[accepted.info["results"][0]["job_id"]].final_artifact_id

        def characterize(request_id):
            return Action(
                "start_operation",
                {
                    "operation_id": "characterize_electrolyte",
                    "input_id": artifact_id,
                    "request_id": request_id,
                    "parameters": {"methods": ["conductivity"]},
                },
            )

        first = env.step(characterize("characterize-a"))
        self.assertTrue(first.info["results"][0]["success"])
        busy = env.step(characterize("characterize-b"))
        self.assertEqual(busy.info["results"][0]["failure_code"], "ARTIFACT_BUSY")
        env.step(Action("advance_time", {"minutes": 45, "request_id": "finish-characterize"}))
        consumed = env.step(characterize("characterize-c"))
        self.assertEqual(consumed.info["results"][0]["failure_code"], "ARTIFACT_CONSUMED")
        self.assertFalse(consumed.info["results"][0]["retryable"])

    def test_parameter_bounds_are_enforced(self):
        env = build_electrolyte_line_env()
        env.reset(seed=42)
        result = env.step(
            Action(
                "start_operation",
                {
                    "operation_id": "mix_electrolyte",
                    "request_id": "invalid-volume",
                    "parameters": {"recipe": RECIPE, "batch_size_ml": 0.0},
                },
            )
        )
        self.assertEqual(result.info["results"][0]["failure_code"], "INVALID_PARAMETER")

    def test_unknown_operation_has_stable_failure_code(self):
        env = build_electrolyte_line_env()
        env.reset(seed=43)
        result = env.step(
            Action(
                "start_operation",
                {
                    "operation_id": "not_registered",
                    "request_id": "unknown-op",
                    "parameters": {},
                },
            )
        )
        self.assertEqual(result.info["results"][0]["failure_code"], "UNKNOWN_OPERATION")

    def test_artifacts_are_episode_isolated(self):
        env = build_electrolyte_line_env()
        env.reset(seed=5)
        accepted = env.step(
            Action(
                "start_operation",
                {
                    "operation_id": "mix_electrolyte",
                    "request_id": "mix-old",
                    "parameters": {"recipe": RECIPE, "batch_size_ml": 10.0},
                },
            )
        )
        env.step(Action("advance_time", {"minutes": 30, "request_id": "advance-old"}))
        old_job = accepted.info["results"][0]["job_id"]
        old_artifact = env.runtime.jobs[old_job].final_artifact_id

        env.reset(seed=6)
        result = env.step(
            Action(
                "start_operation",
                {
                    "operation_id": "characterize_electrolyte",
                    "input_id": old_artifact,
                    "request_id": "cross-episode",
                    "parameters": {"methods": ["conductivity"]},
                },
            )
        )
        self.assertEqual(result.info["results"][0]["failure_code"], "INPUT_NOT_FOUND")

    def test_reward_is_benchmark_configurable(self):
        reward = RewardSpec(version="strict-v1", invalid=-7.0, goal=25.0)
        env = build_electrolyte_line_env(reward=reward)
        env.reset(seed=7)
        invalid = env.step(Action("does_not_exist", {}))
        self.assertEqual(invalid.reward, -7.0)
        self.assertEqual(invalid.info["reward_version"], "strict-v1")

    def test_compiler_rejects_incompatible_chain(self):
        compiler = ProtocolCompiler(build_electrolyte_registry(), electrolyte_resources())
        protocol = ProtocolSpec(
            "invalid-chain",
            (
                ProtocolStep(
                    "mix",
                    "mix_electrolyte",
                    {"recipe": RECIPE, "batch_size_ml": 10.0},
                ),
                ProtocolStep(
                    "formation",
                    "formation_and_capacity",
                    {"protocol": "formation-v1"},
                    "step:mix",
                ),
            ),
        )
        with self.assertRaises(CompilationError):
            compiler.compile(protocol)

    def test_forged_compiled_plan_cannot_bypass_input_chain(self):
        env = build_electrolyte_line_env()
        env.reset(seed=50)
        source_protocol = ProtocolSpec(
            "forged",
            (
                ProtocolStep(
                    "test",
                    "test_cell_batch",
                    {"test_protocol": "capacity-v1"},
                    None,
                ),
            ),
        )
        forged = CompiledProtocol(
            protocol_id="forged",
            steps=(
                CompiledStep(
                    "test",
                    "test_cell_batch",
                    "cell-test-01",
                    {"test_protocol": "capacity-v1"},
                    None,
                ),
            ),
            registry_hash=env.runtime.registry_hash,
            platform_hash=env.runtime.platform_hash,
            source_hash=stable_hash(source_protocol.to_dict()),
            source_protocol=source_protocol,
            total_duration_min=240.0,
            total_cost=55.0,
        )
        result = env.runtime.submit_plan(forged, "forged-plan")
        self.assertFalse(result.success)
        self.assertEqual(result.failure_code, "INVALID_PLAN")
        self.assertEqual(env.runtime.total_cost, 0.0)

    def test_stale_compiled_plan_is_rejected(self):
        env = build_electrolyte_line_env()
        env.reset(seed=51)
        plan = env.runtime.compiler.compile_operation(
            "mix_electrolyte",
            {"recipe": RECIPE, "batch_size_ml": 10.0},
            None,
            env.runtime.artifact_types(),
        )
        stale = replace(plan, registry_hash="sha256:stale")
        result = env.runtime.submit_plan(stale, "stale-plan")
        self.assertEqual(result.failure_code, "INVALID_PLAN")

    def test_non_interruptible_operation_cannot_be_downgraded(self):
        compiler = ProtocolCompiler(build_electrolyte_registry(), electrolyte_resources())
        plan = compiler.compile_operation(
            "inject_and_first_seal",
            {"cell_count": 8},
            "input-1",
            {
                "input-1": {
                    "kind": "characterized_electrolyte",
                    "state": "characterized",
                }
            },
        )
        self.assertFalse(plan.interruptible)

    def test_invalid_time_inputs_do_not_advance_or_create_reward(self):
        reward = RewardSpec(version="time-safe-v1", invalid=-1.0, time_weight=1.0)
        env = build_electrolyte_line_env(reward=reward)
        env.reset(seed=52)
        for index, minutes in enumerate((-100.0, True, float("nan"), float("inf"), "abc")):
            result = env.step(
                Action(
                    "advance_time",
                    {"minutes": minutes, "request_id": "invalid-time-%d" % index},
                )
            )
            self.assertEqual(result.info["results"][0]["failure_code"], "INVALID_PARAMETER")
            self.assertLessEqual(result.reward, 0.0)
            self.assertEqual(env.runtime.clock_min, 0.0)

    def test_time_limit_caps_advance_before_completion(self):
        env = build_electrolyte_line_env()
        env.reset(seed=53)
        env.step(Action("advance_time", {"minutes": 1500, "request_id": "lead-time"}))
        accepted = env.step(skill_action("too-late"))
        job_id = accepted.info["results"][0]["job_id"]
        result = env.step(Action("advance_time", {"minutes": 905, "request_id": "deadline"}))
        self.assertFalse(result.terminated)
        self.assertTrue(result.truncated)
        self.assertEqual(env.runtime.clock_min, 2000.0)
        self.assertEqual(env.runtime.jobs[job_id].status.value, "running")

    def test_submitted_nested_parameters_are_copied(self):
        env = build_electrolyte_line_env()
        env.reset(seed=54)
        recipe = copy.deepcopy(RECIPE)
        accepted = env.step(
            Action(
                "start_operation",
                {
                    "operation_id": "mix_electrolyte",
                    "request_id": "immutable-input",
                    "parameters": {"recipe": recipe, "batch_size_ml": 10.0},
                },
            )
        )
        recipe["components"][0]["material"] = "MUTATED"
        completed = env.step(
            Action("advance_time", {"minutes": 30, "request_id": "finish-immutable"})
        )
        artifact_id = completed.info["results"][0]["produced_artifact_ids"][0]
        stored_recipe = env.runtime.artifacts[artifact_id].metadata["parameters"]["recipe"]
        self.assertEqual(stored_recipe["components"][0]["material"], "EC")
        self.assertTrue(accepted.info["results"][0]["success"])

    def test_completed_idempotent_request_cannot_repeat_reward(self):
        reward = RewardSpec(version="idempotent-v1", completed=2.0)
        env = build_electrolyte_line_env(reward=reward)
        env.reset(seed=55)
        action = Action(
            "start_operation",
            {
                "operation_id": "mix_electrolyte",
                "request_id": "mix-once",
                "parameters": {"recipe": RECIPE, "batch_size_ml": 10.0},
            },
        )
        env.step(action)
        completed = env.step(
            Action("advance_time", {"minutes": 30, "request_id": "finish-mix-once"})
        )
        replay = env.step(action)
        self.assertEqual(completed.reward, 2.0)
        self.assertTrue(replay.info["results"][0]["replayed"])
        self.assertEqual(replay.reward, 0.0)

    def test_scheduler_uses_second_resource_of_same_type(self):
        registry = build_electrolyte_registry()
        resources = electrolyte_resources() + (ResourceSpec("mixer-02", "mixing_station"),)
        runtime = LabRuntime(registry, resources, budget_money=500.0)
        runtime.reset("multi-resource", seed=56)
        first = runtime.submit_operation(
            "mix_electrolyte",
            {"recipe": RECIPE, "batch_size_ml": 10.0},
            None,
            "mix-first",
        )
        second = runtime.submit_operation(
            "mix_electrolyte",
            {"recipe": RECIPE, "batch_size_ml": 10.0},
            None,
            "mix-second",
        )
        self.assertTrue(first.success)
        self.assertTrue(second.success)
        self.assertNotEqual(
            runtime.jobs[first.job_id].plan.steps[0].resource_id,
            runtime.jobs[second.job_id].plan.steps[0].resource_id,
        )

    def test_unknown_skill_step_override_is_rejected(self):
        env = build_electrolyte_line_env()
        env.reset(seed=57)
        action = skill_action("bad-override")
        payload = dict(action.parameters)
        payload["parameters_by_step"] = {"mx": {"recipe": RECIPE, "batch_size_ml": 10.0}}
        result = env.step(Action("start_skill", payload))
        self.assertEqual(result.info["results"][0]["failure_code"], "INVALID_PARAMETER")

    def test_malformed_payload_is_rejected_without_crashing(self):
        env = build_electrolyte_line_env()
        env.reset(seed=58)
        malformed = env.step(
            Action(
                "start_operation",
                {
                    "operation_id": "mix_electrolyte",
                    "request_id": "malformed",
                    "parameters": 5,
                },
            )
        )
        self.assertEqual(malformed.info["results"][0]["failure_code"], "INVALID_PARAMETER")
        non_json = env.step(
            Action(
                "start_operation",
                {
                    "operation_id": "mix_electrolyte",
                    "request_id": "non-json",
                    "parameters": {"recipe": {"materials": {"EC"}}, "batch_size_ml": 10.0},
                },
            )
        )
        self.assertEqual(non_json.info["results"][0]["failure_code"], "INVALID_PARAMETER")

    def test_manifest_mismatch_fails_fast(self):
        env = build_electrolyte_line_env()
        other_task = LabTaskSpec(
            task_id="different-task",
            goal_output_kind="cell_test_report",
            max_steps=40,
            max_time_min=2000.0,
            budget_money=500.0,
        )
        with self.assertRaises(ValueError):
            LabGymEnv(env.runtime, other_task, env.manifest)

    def test_initial_artifact_id_is_not_overwritten(self):
        runtime = LabRuntime(
            build_electrolyte_registry(), electrolyte_resources(), budget_money=500.0
        )
        artifact_id = "collision-electrolyte-batch-0001"
        runtime.reset(
            "collision",
            seed=59,
            initial_artifacts=(
                Artifact(
                    artifact_id=artifact_id,
                    artifact_kind="electrolyte_batch",
                    state="mixed",
                    episode_id="collision",
                    producer_job_id="fixture",
                ),
            ),
        )
        accepted = runtime.submit_operation(
            "mix_electrolyte",
            {"recipe": RECIPE, "batch_size_ml": 10.0},
            None,
            "collision-mix",
        )
        completed = runtime.advance_time(30, "collision-finish")[0]
        self.assertIn(artifact_id, runtime.artifacts)
        self.assertNotEqual(completed.produced_artifact_ids[0], artifact_id)
        self.assertTrue(accepted.success)

    def test_skill_artifacts_record_per_step_completion_times(self):
        env = build_electrolyte_line_env()
        env.reset(seed=60)
        env.step(skill_action("timed-skill"))
        completed = env.step(Action("advance_time", {"minutes": 905, "request_id": "timed-finish"}))
        artifact_ids = completed.info["results"][0]["produced_artifact_ids"]
        times = [
            env.runtime.artifacts[artifact_id].metadata["completed_at_min"]
            for artifact_id in artifact_ids
        ]
        self.assertEqual(times, [30.0, 75.0, 135.0, 615.0, 665.0, 905.0])

    def test_invalid_configuration_is_rejected(self):
        with self.assertRaises(ValueError):
            ResourceSpec("bad", "mixing_station", capacity=0)
        with self.assertRaises(ValueError):
            RewardSpec(time_weight=-1.0)
        with self.assertRaises(ValueError):
            ParameterSpec("string", minimum=1.0)
        with self.assertRaises(ValueError):
            ParameterSpec("array", choices=({1, 2},))
        with self.assertRaises(ValueError):
            OperationSpec(
                "bad-operation",
                "station",
                "output",
                "ready",
                parameters=[],
            )
        with self.assertRaises(ValueError):
            OperationSpec(
                "bad-operation",
                "station",
                "output",
                "ready",
                interruptible="yes",
            )

    def test_observation_cannot_mutate_runtime_or_prior_trace(self):
        env = build_electrolyte_line_env()
        env.reset(seed=61)
        env.step(
            Action(
                "start_operation",
                {
                    "operation_id": "mix_electrolyte",
                    "request_id": "observation-copy",
                    "parameters": {"recipe": RECIPE, "batch_size_ml": 10.0},
                },
            )
        )
        completed = env.step(
            Action("advance_time", {"minutes": 30, "request_id": "observation-finish"})
        )
        artifact_id = completed.info["results"][0]["produced_artifact_ids"][0]
        observed = completed.observation.public_state["artifacts"][artifact_id]
        observed["metadata"]["parameters"]["recipe"]["components"][0]["material"] = "ATTACK"
        runtime_value = env.runtime.artifacts[artifact_id].metadata["parameters"]["recipe"]
        trace_value = env.trace()[-1]["after"]["artifacts"][artifact_id]["metadata"]["parameters"][
            "recipe"
        ]
        self.assertEqual(runtime_value["components"][0]["material"], "EC")
        self.assertEqual(trace_value["components"][0]["material"], "EC")

    def test_huge_integers_are_rejected_without_overflow(self):
        env = build_electrolyte_line_env()
        env.reset(seed=62)
        huge = 10**10000
        time_result = env.step(Action("advance_time", {"minutes": huge, "request_id": "huge-time"}))
        self.assertEqual(time_result.info["results"][0]["failure_code"], "INVALID_PARAMETER")
        parameter_result = env.step(
            Action(
                "start_operation",
                {
                    "operation_id": "mix_electrolyte",
                    "request_id": "huge-parameter",
                    "parameters": {"recipe": RECIPE, "batch_size_ml": huge},
                },
            )
        )
        self.assertEqual(parameter_result.info["results"][0]["failure_code"], "INVALID_PARAMETER")

    def test_protocol_cannot_consume_one_artifact_twice(self):
        env = build_electrolyte_line_env()
        env.reset(seed=63)
        accepted = env.step(
            Action(
                "start_operation",
                {
                    "operation_id": "mix_electrolyte",
                    "request_id": "double-source",
                    "parameters": {"recipe": RECIPE, "batch_size_ml": 10.0},
                },
            )
        )
        env.step(Action("advance_time", {"minutes": 30, "request_id": "double-ready"}))
        artifact_id = env.runtime.jobs[accepted.info["results"][0]["job_id"]].final_artifact_id
        protocol = ProtocolSpec(
            "double-consumption",
            (
                ProtocolStep(
                    "first",
                    "characterize_electrolyte",
                    {"methods": ["density"]},
                    "artifact:%s" % artifact_id,
                ),
                ProtocolStep(
                    "second",
                    "characterize_electrolyte",
                    {"methods": ["conductivity"]},
                    "artifact:%s" % artifact_id,
                ),
            ),
        )
        with self.assertRaises(CompilationError):
            env.runtime.compiler.compile(protocol, env.runtime.artifact_types())

    def test_malformed_compiled_contract_returns_invalid_plan(self):
        env = build_electrolyte_line_env()
        env.reset(seed=64)
        plan = env.runtime.compiler.compile_operation(
            "mix_electrolyte",
            {"recipe": RECIPE, "batch_size_ml": 10.0},
            None,
            env.runtime.artifact_types(),
        )
        malformed_step = copy.deepcopy(plan.steps[0])
        object.__setattr__(malformed_step, "input_ref", 5)
        malformed_plan = replace(plan, steps=(malformed_step,))
        result = env.runtime.submit_plan(malformed_plan, "malformed-plan")
        self.assertEqual(result.failure_code, "INVALID_PLAN")

    def test_reward_implementation_must_match_manifest_contract(self):
        class EvilReward(ConfigurableReward):
            def __call__(self, results, elapsed_min, goal_reached):
                return 999.0

        env = build_electrolyte_line_env()
        with self.assertRaises(ValueError):
            LabGymEnv(
                env.runtime,
                env.task,
                env.manifest,
                reward_model=EvilReward(env.manifest.reward),
            )

    def test_source_hash_tampering_is_rejected(self):
        env = build_electrolyte_line_env()
        env.reset(seed=65)
        plan = env.runtime.compiler.compile_operation(
            "mix_electrolyte",
            {"recipe": RECIPE, "batch_size_ml": 10.0},
            None,
            env.runtime.artifact_types(),
        )
        result = env.runtime.submit_plan(
            replace(plan, source_hash="sha256:tampered"), "tampered-source"
        )
        self.assertEqual(result.failure_code, "INVALID_PLAN")

    def test_completed_skill_replay_returns_all_artifacts(self):
        env = build_electrolyte_line_env()
        env.reset(seed=66)
        parameters = skill_action("full-replay").parameters["parameters_by_step"]
        accepted = env.runtime.submit_skill(
            "run_electrolyte_cell_line", parameters, None, "full-replay"
        )
        completed = env.runtime.advance_time(905, "full-replay-finish")[0]
        replay = env.runtime.submit_skill(
            "run_electrolyte_cell_line", parameters, None, "full-replay"
        )
        self.assertTrue(accepted.success)
        self.assertEqual(len(completed.produced_artifact_ids), 6)
        self.assertEqual(replay.produced_artifact_ids, completed.produced_artifact_ids)
        self.assertTrue(replay.replayed)

    def test_manifest_backend_and_schema_are_bound_to_runtime(self):
        env = build_electrolyte_line_env()
        with self.assertRaises(ValueError):
            LabGymEnv(
                env.runtime,
                env.task,
                replace(env.manifest, backend="real-lab"),
            )
        with self.assertRaises(ValueError):
            LabGymEnv(
                env.runtime,
                env.task,
                replace(env.manifest, schema_version="999"),
            )

    def test_advance_and_stop_requests_are_idempotent(self):
        runtime = LabRuntime(
            build_electrolyte_registry(), electrolyte_resources(), budget_money=500.0
        )
        runtime.reset("control-idempotency", seed=67)
        first_advance = runtime.advance_time(1, "tick-once")[0]
        second_advance = runtime.advance_time(1, "tick-once")[0]
        self.assertTrue(first_advance.success)
        self.assertTrue(second_advance.replayed)
        self.assertEqual(runtime.clock_min, 1.0)

        accepted = runtime.submit_operation(
            "mix_electrolyte",
            {"recipe": RECIPE, "batch_size_ml": 10.0},
            None,
            "stop-target",
        )
        first_stop = runtime.stop_job(accepted.job_id, "stop-once")
        second_stop = runtime.stop_job(accepted.job_id, "stop-once")
        self.assertEqual(first_stop.status, "stopped")
        self.assertEqual(second_stop.status, "stopped")
        self.assertTrue(second_stop.replayed)


if __name__ == "__main__":
    unittest.main()
