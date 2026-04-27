# Project Charter — District Analysis Tool

**Status:** Working draft, April 2026
**Owner:** John Diamant-Boustead, ORG Urbanism & Architecture

## What it is

A web-based, design-exploration tool for the environmental and energy performance of European urban blocks. Users load a block, inspect baseline performance across a focused set of metrics, and modify the design — adding buildings, changing materials, adjusting vegetation — to see how performance shifts. Side-by-side scenario comparison is the core interaction, not an afterthought.

## Who it's for

Internal ORG users during early- and mid-stage design. The primary persona is an architect or urbanist exploring massing and materiality options on a live project. External stakeholder and client-facing modes are deferred.

## What it is not

- Not a strategic planning tool for regional-scale stakeholder engagement.
- Not a specialist simulation tool for defensible absolute numbers (that's Ladybug/Radiance, EnergyPlus, NoiseModelling).
- Not a final-stage design-verification tool. Deep analysis belongs in specialist software; this tool exports to those when needed.
- Not a regional-scale accessibility or transport planning tool.

## Scope for v1

**Study-area scale:** city block — 10 to 50 buildings, ~200m extent.

**Analytical modules, primary-tool quality:**
- Solar radiation (instant + annual)
- Shadows
- Outdoor thermal comfort (UTCI)
- Outdoor wind (simplified, morphology-based)
- Urban heat island (simplified, empirical / UWG)
- Noise (sampling strategic maps + scenario deltas)
- Stormwater (simplified)
- Operational energy (archetype-based)
- Embodied carbon
- Rooftop renewable potential

**Edit operations:** add/modify/remove buildings, change facade and roof materials, add/modify vegetation, change ground surface properties.

**Infrastructure:** scenario management with named, versioned scenarios; baseline-vs-modified diff view; selective result invalidation on edit.

**Geographic focus v1:** Antwerp first, then Ghent, then Brussels.

## Deliberate simplifications

The tool accepts simplified methods where they give the right *ranking* of alternatives, even when absolute numbers are approximate:

- Wind: Lawson pedestrian comfort index, not CFD.
- UHI: empirical / UWG, not mesoscale climate modelling.
- Energy: archetype-based shoebox models, not per-building EnergyPlus.
- Noise: sampling + ISO 9613 deltas, not full CNOSSOS-EU propagation.
- Flooding: hazard-map sampling + impervious-surface delta, not 2D hydraulic modelling.

Every module displays a visible method badge. Users always know what tier of analysis they're looking at. A "Run detailed" option that routes to specialist tools (or batch-mode jobs) is a v2 feature.

## Success criteria

- An ORG designer can load an Antwerp block, make three design variants, and compare them across all ten modules in under 15 minutes of active work.
- Interactive-tier modules respond in under 10 seconds per edit; on-demand-tier modules in under 60 seconds.
- Results for each module are validated against a reference implementation on at least three test blocks. Validation reports are public within the team.
- Every module has a one-page methodology note readable by a client.

## Out of scope for v1

Indoor daylighting, indoor energy (beyond archetype heating/cooling demand), indoor air quality, parking and traffic generation, water use (operational), agriculture, accessibility (transit/walking), microgrid optimisation beyond rule-based sizing, sea level rise.

## Architecture (headline)

- **Backend:** Python (FastAPI), shared geometric kernel, modules as thin layers on the kernel.
- **Frontend:** Web app (built by David), MapLibre GL JS + 3D layer, vanilla JS initially.
- **Storage (v1):** files on a shared drive (GeoPackage for vectors, GeoTIFF for rasters).
- **Storage (later):** PostGIS + object storage when multi-user / multi-site / cloud-hosted access is needed.
- **Data:** through the catalogue, no hardcoded endpoints.
- **Compute model:** pre-compute baseline, interactive deltas, on-demand deeper analysis.

## Open questions

1. Material and vegetation library: build in-house, adapt Honeybee's, or combine?
2. Authorship and versioning of scenarios: named/owned/shareable objects, or session-scoped for v1?
3. Target device: desktop browser only, or laptop-presentable at client meetings?
4. Realistic wall-clock target for v1, given ORG workload.

## Trigger for moving to a database

Files-on-drive is the v1 architecture. Triggers for migrating to a hosted database:

- More than one person regularly editing data simultaneously
- A second city deployed (data volume crosses ~10s of GB)
- A client demo where reproducibility of specific numbers matters
- The web tool moves beyond internal use to multi-organisation deployment

When a trigger is met, the migration is well-scoped because the loader contract isolates storage from everything else.

## Related work to reference

- **Autodesk Forma** (née Spacemaker) — the closest commercial analogue. Worth studying the UX, especially the edit-and-compare loop.
- **Giraffe** — similar space, different positioning. Useful for how they handle scenario management.
- **Ladybug Tools** — not a competitor; a reference implementation to validate against.
- **Tygron** — more comprehensive but at a different scale. Useful for comparing scope choices.
