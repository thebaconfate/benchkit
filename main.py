from pathlib import Path
from benchkit.benches.memcached import MemcachedBench
from benchkit.benches.memcached.campaign import MemcachedCampaign
from benchkit.core.bktypes.contexts import BuildContext, FetchContext, RunContext

bench = MemcachedBench()
bench_dir = Path("~/.benchkit/benches").expanduser().resolve()

fc = FetchContext.from_args(
    fetch_args={
        "parent_dir": bench_dir,
    }
)

fr = fc.call(bench.fetch)


bc = BuildContext.from_fetch(ctx=fc, fetch_result=fr, build_args={})
br = bc.call(bench.build)

rc = RunContext.from_build(
    ctx=bc,
    build_result=br,
    run_args={},
)


rr = rc.call(bench.run)
rc.call(bench.cleanup)
