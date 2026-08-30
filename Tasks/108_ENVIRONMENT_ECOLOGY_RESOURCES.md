# TASK-108 — Climate, Hydrology, Ecology, Resources & Disturbances

## Objective
Deepen the environmental simulation domains on the production world-simulation fabric.

## Existing-work check
Inspect only relevant Shard-116 climate/weather/ecology/resource/Veil/environment code and datasets before extending production.

## Requirements
Implement coherent production models for:
- seasons/day-night/latitude/altitude/winds/rain-shadow/coastal climate;
- rivers/lakes/groundwater/snowpack/drought/flood/water availability;
- flora succession/cohorts/competition/dispersal/disease/fire recovery;
- fauna reproduction/mortality/territory/migration/predation/disease;
- geological/timber/fish/game/herb resource stocks, depletion/regeneration/discovery/quality;
- disturbances such as fire/flood/epidemic/environmental damage and propagation.

Models must respect active/dormant simulation tiers, persistence and event integration. Prefer parameterized deterministic systems over Actor-per-organism designs.

## Acceptance criteria
Representative regions exhibit deterministic seasonal/environmental/resource change, disturbances propagate/recover, persistence round-trips, and gameplay event outputs can be validated automatically.
