"""Runtime DSL primitives for vikhry scenarios."""

from vikhry.runtime.dsl import VU, bind_steps, collect_resource_factories, collect_vu_steps, resource, step

__all__ = [
    "VU",
    "bind_steps",
    "collect_resource_factories",
    "collect_vu_steps",
    "resource",
    "step",
]
