# Simulation, CARLA and learning validation

## Respect native runtime ownership

Inspect the actual installation, matching client ABI, assets, map, renderer,
GPU/runtime availability, process ownership, ports and existing launch/validation
protocol. Use the repository's real commands, not invented launcher arguments.
Do not start a second tick owner or overlapping GPU-heavy runs. Record engine
PID, source/config identity, world/map, scenario/seed, selected controller and
recording IDs. Preserve explicit experiment budgets and protected evaluation data.

A native simulation is not a real-road safety certification. This skill never
authorizes physical vehicle operation.

## Prove that the live loop exists

Observe advancing simulation frames and timestamps, actual native sensor frames,
controller outputs and subsequent measured physical vehicle response. Confirm
the active controller is the claimed rule-based/learned/RL mode. A launch log,
configuration flag, requested command or GPU-memory allocation is not enough.

Record wall-clock duration separately from simulated duration. Report actual
render/physics/control rates as distinct measurements. Check VRAM and GPU usage
where available, but do not force arbitrary utilization thresholds. A CPU-heavy
controller or offscreen renderer can be legitimate; hardware activity alone is
neither proof nor disproof of correct driving.

Show the visible simulation/dashboard when permitted, otherwise clearly label
headless/offscreen operation and inspect genuinely captured sensor/video frames.
Do not substitute saved media or synthetic browser telemetry for a new run.

## Use the correct test progression

Reproduce the issue in the smallest relevant permitted native experiment. Repair
one evidence-supported cause, run useful offline regressions, then repeat the
actual native action. Use a bounded smoke test to establish readiness, not to
replace the original full-route requirements.

Follow the project's development/diagnostic/holdout order. Execute the full
required route or episode and required mode comparisons before acceptance.
Keep initial conditions and seeds comparable where the experiment requires it.
Preserve failed/crashed/timeout runs and scoring populations. Never select only
a favorable seed or edit the outcome to obtain acceptance.

For each driving claim distinguish: maneuver requested, maneuver admitted,
control submitted, physical displacement observed, full maneuver completed and
route terminal outcome. Safe stopping can pass a safety subcase while failing
route completion. Zero contacts in a short prefix does not prove a full trip.

## Measure the actual criteria

Use the existing acceptance contract. Depending on the goal, observe route
completion, collisions/contacts, near misses, stops/restarts, pedestrian responses,
physical lane change/overtake/return, sensor freshness, actual timing, resource
usage and clean shutdown/export. Do not weaken speed, timing, safety, density or
coverage requirements to obtain a green result.

Treat controller decisions and independent scoring separately. Do not silently
replace sensor inputs with privileged simulator ground truth. Ground truth may
be appropriate for clearly labeled scoring, not for pretending perception works.
Record original observations, scoring implementation and scenario identifiers.

## RL and ML are separate claims

Do not assume RL is running because files named `rl` exist. Identify the actual
training entry point, environment interaction, optimizer steps, changing weights,
checkpoints, evaluation protocol and device. Distinguish training from inference,
behavior cloning from reinforcement learning, replay from fresh interaction and
rule-based decisions from learned control.

For a training task, verify meaningful interaction and updates, then evaluate a
frozen checkpoint on the allowed separate evaluation split using the existing
criteria. A reward curve or busy GPU is not sufficient. Do not launch new costly
training simply because a UI/simulation task was requested.

## Package evidence without fabricating adapters

Use the existing native harness and scoring exports where possible. A task-specific
adapter may copy raw artifacts into `PROVE_IT_OUTPUT_DIR` and parse real metrics;
it must not manufacture success JSON or run a mock simulation. Include adapter
source and scoring rules in the fingerprint. Keep large source recordings in
the approved storage location; collect necessary bounded evidence or verified
manifest references without deleting originals.

For each run preserve launch command, source and environment, process identity,
frame/timing traces, real distance/route outcome, sensor/controller identity,
collisions, actual video and cleanup evidence. Missing access is BLOCKED_UNVERIFIED,
not a reason to reset ledgers, bypass policies or pretend replay is live.
