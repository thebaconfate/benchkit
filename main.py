from benchkit.benches.memcached import MemcachedBench
from benchkit.benches.memcached.campaign import MemcachedCampaign
from benchkit.core.compat.new2old import CampaignCartesianProduct

variables = {
    "nb_threads": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    "run_count": [30],
    "pipeline": [1, 2, 3, 4, 5, 6],
    "nb_clients": [10, 20, 30, 40, 50, 60, 70, 80, 100],
    "ratio": [
        "1:10",
        "2:10",
        "3:10",
        "4:10",
        "5:10",
        "6:10",
        "7:10",
        "8:10",
        "9:10",
        "10:10",
    ],
    "key_pattern": ["R:R", "G:G", "S:S", "P:P", "Z:Z"],
    "data_size": [8, 16, 32, 64],
    "key_minimum": [0, 1],
}

campaign = CampaignCartesianProduct(
    benchmark=MemcachedBench(),
    variables=variables,
)

campaign.run()
