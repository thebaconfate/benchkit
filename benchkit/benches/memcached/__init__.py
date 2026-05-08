""" """

from pathlib import Path
from benchkit.core.bktypes.callresults import BuildResult, FetchResult, RunResult
from benchkit.core.bktypes.contexts import BuildContext, FetchContext, RunContext
from benchkit.utils.dir import get_benches_dir
from benchkit.utils.fetchtools import git_clone
from benchkit.utils.buildtools import make


class MemcachedBench:
    def fetch(self, ctx: FetchContext, parent_dir: Path | None = None) -> FetchResult:
        parent_dir = get_benches_dir(parent_dir=parent_dir)
        leveldb_dir = git_clone(
            ctx=ctx,
            url="https://github.com/redis/memtier_benchmark.git",
            commit="378cbb9f573916c1eeca9158c66047cea232dbcd",
            parent_dir=parent_dir,
        )

        ctx.exec(
            argv=["git", "checkout", "master"],
            cwd=leveldb_dir,
            output_is_log=True,
        )

        return FetchResult(src_dir=leveldb_dir)

    def build(
        self,
        ctx: BuildContext,
    ) -> BuildResult:
        """
        autoreconf -ivf
        ./configure
        make
        sudo make install
        """
        ctx.exec(argv=["autoreconf", "-ivf"])
        ctx.exec(argv=["./configure"])
        src_dir = ctx.fetch_result.src_dir
        make(ctx, src_dir=src_dir, targets=[], options={})
        make(ctx, src_dir=src_dir, targets=["install"], options={})
        build_dir = src_dir / "bin"
        result = BuildResult(
            build_dir=build_dir,
        )
        return result

    def run(
        self,
        ctx: RunContext,
        nb_threads: int = 2,
        test_name: str = "lu",
        t_class: str = "A",
    ) -> RunResult:
        pass
