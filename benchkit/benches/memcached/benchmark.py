""" """

from pathlib import Path
import re
from benchkit.core.bktypes import RecordResult
from benchkit.core.bktypes.callresults import BuildResult, FetchResult, RunResult
from benchkit.core.bktypes.contexts import (
    BuildContext,
    CollectContext,
    FetchContext,
    RunContext,
)
from benchkit.dependencies.packages import PackageDependency
from benchkit.utils.dir import get_benches_dir
from benchkit.utils.fetchtools import git_clone
from benchkit.utils.buildtools import build_dir_from_ctx, make


class MemcachedBench:
    def fetch(self, ctx: FetchContext, parent_dir: Path | None = None) -> FetchResult:
        """
        Fetch memtier_benchmark source code from GitHub.

        Clones the memtier_benchmark repository and checks out a specific commit
        before ensuring the local workspace is on the master branch.

        Args:
            ctx: FetchContext providing platform and execution capabilities.
            parent_dir: Directory where the memtier_benchmark repository will be cloned.

        Returns:
            FetchResult containing the path to the cloned repository.
        """
        parent_dir = get_benches_dir(parent_dir=parent_dir)
        memcached_dir = git_clone(
            ctx=ctx,
            url="https://github.com/redis/memtier_benchmark.git",
            commit="378cbb9f573916c1eeca9158c66047cea232dbcd",
            parent_dir=parent_dir,
        )
        return FetchResult(src_dir=memcached_dir)

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
        platform = ctx.platform
        src_dir = ctx.fetch_result.src_dir
        obj_dir = build_dir_from_ctx(ctx=ctx)
        memcached_bench_path = obj_dir / "memcached_bench"
        tmpdb_dir = obj_dir / "tmp" / "benchkit_memcached"
        if not platform.comm.isfile(memcached_bench_path):
            ctx.exec(argv=["autoreconf", "-ivf"], cwd=obj_dir, output_is_log=True)
            ctx.exec(argv=["./configure"], cwd=obj_dir, output_is_log=True)
            make(ctx, src_dir=src_dir, targets=[], options={})
            make(ctx, src_dir=src_dir, targets=["install"], options={})
        if not platform.comm.isdir(tmpdb_dir):
            platform.comm.makedirs(path=tmpdb_dir, exist_ok=True)
            ctx.exec(
                argv=[
                    "./db_bench",
                    "--threads=1",
                    "--benchmarks=fillseq",
                    f"--db={tmpdb_dir}",
                ],
                cwd=obj_dir,
                output_is_log=True,
            )

        result = BuildResult(
            build_dir=obj_dir,
            other={
                "tmpdb_dir": tmpdb_dir,
            },
        )
        src_dir = ctx.fetch_result.src_dir
        build_dir = src_dir / "bin"
        result = BuildResult(
            build_dir=build_dir,
        )
        return result

    def run(
        self,
        ctx: RunContext,
        bench_name: str,
        nb_threads: int = 2,
        nb_iterations: int = 40000,
    ) -> RunResult:
        """
        TODO: add comments like in leveldb
        """
        use_existing_db = True
        duration_s = ctx.duration_s
        build_dir = ctx.build_result.build_dir
        tmpdb_dir = ctx.build_result.other["tmpdb_dir"]
        workload_args = (
            [f"--duration={duration_s}"]
            if duration_s is not None
            else [f"--num={nb_iterations}"]
        )

        run_command = [
            "./db_bench",
            f"--threads={nb_threads}",
            f"--benchmarks={bench_name}",
            f"--use_existing_db={'1' if use_existing_db else '0'}",
            f"--db={tmpdb_dir}",
            *workload_args,
        ]

        exec_out = ctx.exec(argv=run_command, cwd=build_dir, output_is_log=True)

        result = RunResult(outputs=[exec_out])
        return result

    def collect(
        self,
        ctx: CollectContext,
        bench_name: str,
    ) -> RecordResult:
        """
        Parse performance metrics from LevelDB db_bench output.

        This collector is tailored to a patched LevelDB db_bench that emits a
        thread-aware statistics line of the form:

            benchstats:<duration>;<global_count>;<thread_0>;...;<thread_{N-1}>

        where:
            - <duration> is the total execution time reported by db_bench
            - <global_count> is the total number of operations executed
            - <thread_i> is the number of operations executed by thread i

        In addition, the standard db_bench summary line is parsed when present,
        for example:

            readrandom : 1.841 micros/op; (539804 of 1000000 found)

        This line is used to extract per-operation latency and, for read
        benchmarks, the number of keys found.

        Args:
            ctx: CollectContext providing access to the run output produced by
                db_bench.
            bench_name: Name of the benchmark that was run (e.g., "readrandom"),
                used to identify the relevant summary line.

        Returns:
            Dictionary containing parsed metrics, including:
                - duration: Normalized execution time in seconds (derived from
                  benchstats and divided by the number of threads).
                - global_count: Total number of operations performed.
                - operations/second: Throughput in operations per second, computed
                  as global_count / duration.
                - microseconds/operation: Average latency per operation, extracted
                  from the db_bench summary line when available.
                - thread_i: Number of operations executed by thread i (one entry
                  per thread).
                - ofleft: Number of keys found (for read benchmarks, if reported).
                - ofright: Total number of keys searched for (for read benchmarks,
                  if reported).
                - duration_s: Total wall-clock execution time in seconds

        Raises:
            ValueError: If the expected benchstats line is missing or inconsistent
                with the number of threads, indicating incoherent db_bench output.

        Example output:
            {
                "duration": 1.0,
                "global_count": 1629644,
                "operations/second": 1629644.0,
                "microseconds/operation": 1.841,
                "thread_0": 542781,
                "thread_1": 539804,
                "thread_2": 547059,
                "ofleft": 539804,
                "ofright": 1000000,
            }
        """
        output = ctx.run_result.outputs[-1].stdout

        # ------------------------------------------------------------------
        # 1) Parse patched benchstats line
        # ------------------------------------------------------------------
        if "benchstats:" not in output:
            raise ValueError(
                f"Incoherent output from leveldb (missing benchstats line):\n{output}"
            )

        benchstats = output.split("benchstats:")[-1].strip()
        values = benchstats.split(";")

        # Infer number of threads from benchstats format:
        # duration + global_count + N thread fields
        if len(values) < 3:
            raise ValueError(
                f"Incoherent benchstats format, expected at least 3 fields:\n{output}"
            )

        nb_threads = len(values) - 2

        names = ["duration", "global_count"] + [
            f"thread_{k}" for k in range(nb_threads)
        ]
        raw = dict(zip(names, values))

        try:
            duration_raw = float(raw["duration"])
            global_count = int(float(raw["global_count"]))
        except ValueError as e:
            raise ValueError(
                f"Failed to parse numeric benchstats values:\n{output}"
            ) from e

        # Historical normalization: duration is divided by number of threads
        duration = duration_raw / nb_threads if nb_threads > 0 else duration_raw

        record: RecordResult = {
            "duration": duration,
            "global_count": global_count,
            "operations/second": (global_count / duration) if duration > 0 else 0.0,
        }

        # Per-thread operation counts
        for k in range(nb_threads):
            try:
                record[f"thread_{k}"] = int(float(raw[f"thread_{k}"]))
            except ValueError as e:
                raise ValueError(
                    f"Failed to parse per-thread count for thread {k}:\n{output}"
                ) from e

        # ------------------------------------------------------------------
        # 2) Parse standard db_bench summary line (latency + found info)
        # ------------------------------------------------------------------
        #
        # Example:
        #   readrandom : 1.841 micros/op; (539804 of 1000000 found)
        #
        summary_re = re.search(
            rf"^{re.escape(bench_name)}\s*:\s*"
            rf"(?P<microspop>[0-9]*\.?[0-9]+)\s+micros/op;?\s*"
            rf"(?:\(\s*(?P<ofleft>\d+)\s+of\s+(?P<ofright>\d+)\s+found\s*\))?",
            output,
            flags=re.MULTILINE,
        )

        if summary_re:
            record["microseconds/operation"] = float(summary_re.group("microspop"))

            if summary_re.group("ofleft") is not None:
                record["ofleft"] = int(summary_re.group("ofleft"))
                record["ofright"] = int(summary_re.group("ofright"))

        duration_s = ctx.run_result.outputs[-1].duration_s
        record["duration_s"] = duration_s

        return record

    @staticmethod
    def dependencies() -> list[PackageDependency]:
        """
        List system package dependencies required to build and run memcached.
        source: https://github.com/redis/memtier_benchmark/blob/master/DEVELOPMENT.md

        Returns:
            List of PackageDependency objects for required system packages.
            These are Ubuntu/Debian package names; other distributions may have
            different package names.

        Dependencies include:
            - build-essential: C/C++ compiler and standard build tools (includes make)
            - autoconf: Tool for generating configuration scripts
            - automake: Tool for generating standard Makefiles
            - libevent-dev: Event notification library (crucial for Redis/Memcached networking)
            - pkg-config: Helper tool used when compiling applications and libraries
            - zlib1g-dev: Compression library (header files and development headers)
            - libssl-dev: SSL/TLS encryption and cryptography libraries
            - clang-format: Tool to format C/C++/Java/JavaScript/Objective-C/Protobuf code
            - redis-server: The program on which we'll be running our benchmark
              against.
        """
        return [
            PackageDependency("install"),
            PackageDependency("build-essential"),
            PackageDependency("autoconf"),
            PackageDependency("automake"),
            PackageDependency("libevent-dev"),
            PackageDependency("pkg-config"),
            PackageDependency("zlib1g-dev"),
            PackageDependency("libssl-dev"),
            PackageDependency("clang-format"),
            PackageDependency("redis-server"),
        ]
