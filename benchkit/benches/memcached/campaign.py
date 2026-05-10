from typing import Any, Dict, Iterable

from benchkit.benches.memcached.benchmark import MemcachedBench
from benchkit.commandwrappers.perf import PerfStatWrap
from benchkit.core.compat.new2old import CampaignCartesianProduct
from benchkit.platforms import get_current_platform


def MemcachedCampaign(variables: Dict[str, Iterable[Any]], **kwargs):
    """ """

    platform = get_current_platform()
    events = ["cache-misses", "instructions", "cycles"]
    perfstatwrap = PerfStatWrap(
        events=events,
        use_json=True,
        aggregate_hybrid=True,
        platform=platform,
    )
    return CampaignCartesianProduct(
        benchmark=MemcachedBench(),
        variables=variables,
        command_wrappers=[perfstatwrap],
        post_run_hooks=[perfstatwrap.post_run_hook_update_results],
        **kwargs,
    )
