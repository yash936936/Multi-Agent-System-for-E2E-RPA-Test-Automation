"""
DataSynth tool registration.

Resolved by the kernel via config/tool_registry.yaml:
    DataSynth.generate -> agents.data_synth.tool.generate

Checks the cache first (agents/data_synth/cache.py) before generating
fresh data, per TRD §2.4's "generate once per test, reuse across runs"
policy. Pass refresh=True via a direct call (not through the kernel's
strict schema) to force regeneration — the CLI's `--refresh-data` flag
(Phase 6) will do this by calling generate_data directly rather than the
cached wrapper.
"""
from __future__ import annotations

from agents.data_synth.cache import load_cached, save_cache
from agents.data_synth.generator import generate_data
from orchestrator.schemas import DataRequirements, SyntheticDataRecord


def generate(payload: DataRequirements) -> SyntheticDataRecord:
    if payload.test_id:
        cached = load_cached(payload.test_id)
        if cached is not None:
            # D-XXX fix: the cache is keyed only on test_id, but a spec's
            # data_requirements can grow between runs (e.g. the planner
            # starts asking for "username" on a test_id that was already
            # cached without it). Returning the stale dict verbatim would
            # silently drop the new field for every downstream consumer.
            # Fill in only what's missing so previously-cached values stay
            # stable (per TRD §2.4) while new fields still get generated.
            missing = [f for f in payload.fields if f not in cached]
            if missing:
                cached = {**cached, **generate_data(missing)}
                save_cache(payload.test_id, cached)
            return SyntheticDataRecord(test_id=payload.test_id, values=cached)

    values = generate_data(payload.fields)

    if payload.test_id:
        save_cache(payload.test_id, values)

    return SyntheticDataRecord(test_id=payload.test_id, values=values)
