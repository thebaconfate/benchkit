from pathlib import Path
from benchkit.benches.leveldb import LevelDBBench

from benchkit.core.bktypes.contexts import (
    BuildContext,
    CollectContext,
    FetchContext,
    RunContext,
)


bench = LevelDBBench()

bench_dir = Path("~/.benchkit/benches").expanduser().resolve()

fc = FetchContext.from_args(fetch_args={"parent_dir": bench_dir})
fr = fc.call(bench.fetch)

bc = BuildContext.from_fetch(ctx=fc, fetch_result=fr, build_args={})
br = bc.call(bench.build)

rc = RunContext.from_build(
    ctx=bc, build_result=br, run_args={"bench_name": "readrandom"}
)
rr = rc.call(bench.run)

cc = CollectContext.from_run(ctx=rc, run_result=rr)
result = cc.call(bench.collect)
print(result)
