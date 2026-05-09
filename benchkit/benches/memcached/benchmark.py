""" """

from pathlib import Path
import re
from typing import Literal
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
        Build memtier_benchmark from source.

        Runs the GNU Autotools sequence (autoreconf, configure, and make)
        to compile the memtier_benchmark binary if it does not already
        exist in the source directory.

        Args:
            ctx: BuildContext providing fetch results and platform capabilities.

        Returns:
            BuildResult containing the path to the directory where the
            binary was built.
        """
        platform = ctx.platform
        src_dir = ctx.fetch_result.src_dir
        memcached_bench_path = src_dir / "memcached_bench"
        if not platform.comm.isfile(memcached_bench_path):
            ctx.exec(argv=["autoreconf", "-ivf"], cwd=src_dir, output_is_log=True)
            ctx.exec(argv=["./configure"], cwd=src_dir, output_is_log=True)
            make(ctx, src_dir=src_dir, targets=[], options={})
        # if not platform.comm.isdir(tmpdb_dir):
        # platform.comm.makedirs(path=tmpdb_dir, exist_ok=True)

        result = BuildResult(
            build_dir=src_dir,
        )
        return result

    def cleanup(self, ctx: RunContext):
        """
        Reset the target database to ensure a clean state for subsequent runs.

        Executes a FLUSHDB command via redis-cli to remove all existing keys
        from the current Redis database. This prevents data pollution and
        interference between different benchmark iterations.

        Args:
            ctx: RunContext providing the communication layer to execute
                 the cleanup command.
        """
        ctx.exec(argv=["redis-cli", "FLUSHDB"], output_is_log=True)

    def run(
        self,
        ctx: RunContext,
        server_ip: str = "localhost",
        server_port: str = "6379",
        protocol: str = "redis",
        authenticate: str | None = None,
        cluster_mode: bool = False,
        requests: int | Literal["allKeys"] = 10000,
        nb_clients: int = 50,
        nb_threads: int = 4,
        run_count: int = 1,
        test_time: int | None = None,
        pipeline: int = 1,
        ratio: str = "1:10",
        key_pattern: str = "R:R",
        data_size: int = 32,
        key_minimum: int = 0,
        key_maximum: int = 10000000,
        **kwargs,
    ) -> RunResult:
        """
        Execute a memtier_benchmark run with the specified workload parameters.

        This method assembles the command-line arguments for memtier_benchmark.
        It supports both explicit high-level parameters and arbitrary
        pass-through arguments via kwargs. The flags of kwargs should be passed as
        flag and not as --flag

        Args:
            ctx: RunContext providing execution and platform capabilities.
            server_ip: IP address of the target server.
            server_port: Port of the target server.
            protocol: Protocol to use (redis, resp2, resp3, memcache_text, etc.).
            authenticate: Credentials for server authentication.
            cluster_mode: If True, runs the client in Redis cluster mode.
            requests: Total requests per client or 'allKeys' for the full range.
            nb_clients: Number of clients to simulate per thread.
            nb_threads: Number of parallel threads to use.
            run_count: Number of full-test iterations to perform.
            test_time: Duration of the test in seconds.
            pipeline: Number of concurrent pipelined requests.
            ratio: Set:Get ratio of the workload.
            key_pattern: Distribution pattern (Gaussian, Random, Zipf, etc.).
            data_size: Size of the object data in bytes.
            key_minimum: Minimum ID value for keys.
            key_maximum: Maximum ID value for keys.
            **kwargs: Additional memtier_benchmark flags (e.g., randomize=True).

        Returns:
            RunResult containing the execution output and performance data.
        """
        run_command = [
            "./memtier_benchmark",
            f"--server={server_ip}",
            f"--port={server_port}",
            f"--protocol={protocol}",
            f"--authenticate={authenticate}" if authenticate is not None else "",
            f"--cluster-mode" if cluster_mode else "",
            f"--requests={requests}",
            f"--clients={nb_clients}",
            f"--threads={nb_threads}",
            f"--run-count={run_count}",
            f"--test-time={test_time}" if test_time is not None else "",
            f"--pipeline={pipeline}",
            f"--ratio={ratio}",
            f"--key-pattern={key_pattern}",
            f"--data-size={data_size}",
            f"--key-minimum={key_minimum}" if key_minimum > 0 else "",
            f"--key-maximum={key_maximum}",
        ]
        flags = {
            item.split("=")[0].lstrip("-")
            for item in run_command
            if item.startswith("-")
        }

        for key, value in kwargs.items():
            if key not in flags:
                flag = key.replace("_", "-")
                if isinstance(value, bool) and value is True:
                    run_command.append(f"--{flag}")
                elif isinstance(value, (int, str)):
                    run_command.append(f"--{flag}={value}")
                else:
                    ctx.platform.comm.shell(
                        " ".join(
                            [
                                "echo",
                                '"[DEBUG] Unknown kwargs passed to run',
                                f"with key: {key} ",
                                f'and value: {value}"',
                            ]
                        )
                    )
        build_dir = ctx.build_result.build_dir
        run_command = [cmd for cmd in run_command if cmd != ""]
        exec_out = ctx.exec(argv=run_command, cwd=build_dir, output_is_log=True)
        result = RunResult(outputs=[exec_out])
        return result

    def collect(
        self,
        ctx: CollectContext,
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
        output = [
            line for line in ctx.run_result.outputs[-1].stdout.split("\n") if line != ""
        ]
        threads = int(output[0].split()[0])
        connections_per_thread = int(output[1].split()[0])
        requests_per_client = int(output[2].split()[0])
        start_stats_idx = output.index("ALL STATS") + 2  # skip the ---- line
        start_dist_idx = output.index("Request Latency Distribution") + 1

        # Parsing the ALL STATS table
        all_stats_headers = output[start_stats_idx].split()

        def parseFloat(value):
            try:
                return float(value)
            except ValueError:
                return value

        all_stats_rows = [
            [parseFloat(data) if "-" not in data else None for data in row.split()]
            for row in output[start_stats_idx + 2 : start_dist_idx - 1]
        ]
        # skips the --- line after the headers and collects the table rows till
        # the dist table

        # Parsing the Request Latency Distribution table
        dist_headers = output[start_dist_idx].split()
        dist_rows = [
            [parseFloat(data) for data in row.split()]
            for row in output[start_dist_idx + 1 :]
            if "-" not in row
        ]
        result: RecordResult = {
            "threads": threads,
            "connections_per_thread": connections_per_thread,
            "requests_per_client": requests_per_client,
            "all_stats_headers": all_stats_headers,
            "all_stats_rows": all_stats_rows,
            "dist_headers": dist_headers,
            "dist_rows": dist_rows,
        }
        return result

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
