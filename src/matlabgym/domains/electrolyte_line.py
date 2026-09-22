"""Six-stage electrolyte line from the MatLabGYM lab interface template."""

from __future__ import annotations

from typing import Optional, Tuple

from ..lab import (
    EnvironmentManifest,
    LabGymEnv,
    LabRuntime,
    LabTaskSpec,
    OperationSpec,
    ParameterSpec,
    ResourceSpec,
    RewardSpec,
    SkillRegistry,
    SkillSpec,
    SkillStep,
)
from ..lab.registry import platform_hash


def build_electrolyte_registry() -> SkillRegistry:
    registry = SkillRegistry()
    owner = "battery-platform-owner"
    source = "MATLABGYM LAB simulation interface template"

    registry.register_operation(
        OperationSpec(
            operation_id="mix_electrolyte",
            resource_type="mixing_station",
            output_kind="electrolyte_batch",
            output_state="mixed",
            parameters={
                "recipe": ParameterSpec("object"),
                "batch_size_ml": ParameterSpec("number", unit="mL", minimum=1.0, maximum=1000.0),
            },
            duration_min=30.0,
            cost=12.0,
            interruptible=True,
            owner=owner,
            provenance=source,
        )
    )
    registry.register_operation(
        OperationSpec(
            operation_id="characterize_electrolyte",
            resource_type="electrolyte_characterization_station",
            input_kind="electrolyte_batch",
            input_state="mixed",
            output_kind="characterized_electrolyte",
            output_state="characterized",
            parameters={"methods": ParameterSpec("array")},
            duration_min=45.0,
            cost=20.0,
            interruptible=True,
            owner=owner,
            provenance=source,
        )
    )
    registry.register_operation(
        OperationSpec(
            operation_id="inject_and_first_seal",
            resource_type="injection_sealing_station",
            input_kind="characterized_electrolyte",
            input_state="characterized",
            output_kind="first_sealed_cell_batch",
            output_state="first_sealed",
            parameters={"cell_count": ParameterSpec("integer", minimum=1, maximum=96)},
            duration_min=60.0,
            cost=35.0,
            interruptible=False,
            owner=owner,
            provenance=source,
        )
    )
    registry.register_operation(
        OperationSpec(
            operation_id="formation_and_capacity",
            resource_type="formation_station",
            input_kind="first_sealed_cell_batch",
            input_state="first_sealed",
            output_kind="formed_cell_batch",
            output_state="formed",
            parameters={"protocol": ParameterSpec("string")},
            duration_min=480.0,
            cost=80.0,
            interruptible=False,
            owner=owner,
            provenance=source,
        )
    )
    registry.register_operation(
        OperationSpec(
            operation_id="second_fill_and_degas",
            resource_type="degas_station",
            input_kind="formed_cell_batch",
            input_state="formed",
            output_kind="degassed_cell_batch",
            output_state="degassed",
            parameters={
                "vacuum_kpa": ParameterSpec("number", unit="kPa", minimum=1.0, maximum=101.0)
            },
            duration_min=50.0,
            cost=30.0,
            interruptible=False,
            owner=owner,
            provenance=source,
        )
    )
    registry.register_operation(
        OperationSpec(
            operation_id="test_cell_batch",
            resource_type="cell_test_station",
            input_kind="degassed_cell_batch",
            input_state="degassed",
            output_kind="cell_test_report",
            output_state="completed",
            parameters={"test_protocol": ParameterSpec("string")},
            duration_min=240.0,
            cost=55.0,
            interruptible=True,
            owner=owner,
            provenance=source,
        )
    )

    registry.register_skill(
        SkillSpec(
            skill_id="run_electrolyte_cell_line",
            steps=(
                SkillStep("mix", "mix_electrolyte"),
                SkillStep(
                    "characterize",
                    "characterize_electrolyte",
                    {"methods": ["density", "conductivity"]},
                ),
                SkillStep("first_seal", "inject_and_first_seal", {"cell_count": 8}),
                SkillStep("formation", "formation_and_capacity", {"protocol": "formation-v1"}),
                SkillStep("degas", "second_fill_and_degas", {"vacuum_kpa": 80.0}),
                SkillStep("test", "test_cell_batch", {"test_protocol": "capacity-v1"}),
            ),
            interruptible=False,
            owner=owner,
        )
    )
    return registry


def electrolyte_resources() -> Tuple[ResourceSpec, ...]:
    return (
        ResourceSpec("mixer-01", "mixing_station"),
        ResourceSpec("characterization-01", "electrolyte_characterization_station"),
        ResourceSpec("injection-seal-01", "injection_sealing_station"),
        ResourceSpec("formation-01", "formation_station", capacity=2),
        ResourceSpec("degas-01", "degas_station"),
        ResourceSpec("cell-test-01", "cell_test_station", capacity=2),
    )


def build_electrolyte_line_env(
    reward: Optional[RewardSpec] = None,
) -> LabGymEnv:
    reward = reward or RewardSpec(
        version="electrolyte-line-reward-v1",
        accepted=0.0,
        completed=0.2,
        invalid=-1.0,
        stopped=-0.2,
        goal=10.0,
        cost_weight=0.001,
        time_weight=0.0,
    )
    registry = build_electrolyte_registry()
    resources = electrolyte_resources()
    task = LabTaskSpec(
        task_id="electrolyte.line.complete.v1",
        goal_output_kind="cell_test_report",
        max_steps=40,
        max_time_min=2000.0,
        budget_money=500.0,
    )
    manifest = EnvironmentManifest(
        task=task,
        registry_hash=registry.snapshot_hash,
        platform_hash=platform_hash(resources),
        reward=reward,
    )
    runtime = LabRuntime(registry, resources, budget_money=task.budget_money)
    return LabGymEnv(runtime, task, manifest)
