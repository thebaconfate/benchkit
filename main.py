from benchkit.benches.memcached import MemcachedBench
from benchkit.benches.memcached.campaign import MemcachedCampaign
from benchkit.core.compat.new2old import CampaignCartesianProduct

variables = {"nb_threads": [1, 2, 3, 4]}

campaign = CampaignCartesianProduct(
    benchmark=MemcachedBench(),
    variables=variables,
)

campaign.run()
