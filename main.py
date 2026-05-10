from benchkit.benches.memcached.campaign import MemcachedCampaign
from benchkit.campaign import CampaignSuite
from benchkit.commandwrappers.perf import PerfStatWrap
from benchkit.platforms import get_current_platform
from tests.campaigns.campaign_perf_cartprod import make_perfstat_process_dataframe

variables = {
    "nb_threads": [i for i in range(1, 13)],
    "key_pattern": ["G:G"],
}


campaign = MemcachedCampaign(
    variables=variables,
    **{
        "nb_runs": 30,
    },
)


campaigns = [campaign]
suite = CampaignSuite(campaigns=campaigns)
suite.run_suite()
suite.generate_graph(plot_name="lineplot", x="nb_threads", y="throughput")
suite.generate_graph(
    plot_name="scatterplot", x="perf-stat/cycles", y="perf-stat/instructions"
)
suite.generate_graph(plot_name="barplot", x="nb_threads", y="perf-stat/cache-misses")
