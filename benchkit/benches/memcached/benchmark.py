from pathlib import Path
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
from benchkit.utils.buildtools import make


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

    def _start_up_redis(self, ctx: RunContext):
        """
        Starts up redis

        Args:
            ctx: RunContext providing the communication layer to execute the
            start redis command
        """
        ctx.exec(argv=["systemctl", "start", "redis"], output_is_log=True)

    def _cleaup_redis(self, ctx: RunContext):
        """
        Reset the target database to ensure a clean state for subsequent runs.

        Executes a FLUSHDB command via redis-cli to remove all existing keys
        from the current Redis database. This prevents data pollution and
        interference between different benchmark iterations.

        Args:
            ctx: RunContext providing the communication layer to execute
                 the cleanup command.
        """
        ctx.exec(argv=["redis-cli", "FLUSHALL"], output_is_log=True)

    def _stop_redis(self, ctx: RunContext):
        """
        Stop redis

        Args:
            ctx: RunContext providing the communication layer to execute the
            stop redis command
        """
        ctx.exec(argv=["systemctl", "stop", "redis"], output_is_log=True)

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

        Returns:
            RunResult containing the execution output and performance data.
        """
        run_command = [
            "./memtier_benchmark",
            f"--server={server_ip}",
            f"--port={server_port}",
            f"--protocol={protocol}",
            f"--authenticate={authenticate}" if authenticate is not None else "",
            "--cluster-mode" if cluster_mode else "",
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

        build_dir = ctx.build_result.build_dir
        run_command = [cmd for cmd in run_command if cmd != ""]
        exec_out = ctx.exec(argv=run_command, cwd=build_dir, output_is_log=True)
        result = RunResult(outputs=[exec_out])
        self._cleaup_redis(ctx)
        return result

    def collect(
        self,
        ctx: CollectContext,
    ) -> RecordResult:
        """
        Parse performance metrics from memtier_benchmark output.

        This collector is tailored to the output generated by the benchmark when
        using --run-count=1.
        eg:

            <threads> Threads
            <connections_per_thread> Connections per thread
            <requests_per_client> Requests per client

            ALL STATS
            =====...
            <all_stats_headers>
            -----...
            [<all_stats_row>, ...]


            Request Latency Distribution
            <dist_headers>
            ---...
            [<dist_row>, ...]

        It currently does NOT support the output generated by using
        --run-count=<COUNT> where COUNT > 1. In this case the results are
        aggregated and the table is different.


        where:
            - <threads> is the total amount of threads used in the benchmark run
            - <connections_per_thread> Clients per thread
            - <requests_per_client> Requests made per client
            - <all_stats_headers> headers of the ALL STATS table
            - <all_stats_row> a row of the ALL STATS table
            - <dist_headers> headers of the Request Latency Distribution
            - <dist_row> a row of the Request Latency Distribution table


        Args:
            ctx: CollectContext providing access to the run output produced by
                db_bench.
            "threads": threads,
            "connections_per_thread": connections_per_thread,
            "requests_per_client": requests_per_client,
            ""

        Type         Ops/sec     Hits/sec   Misses/sec    Avg. Latency     p50 Latency     p99 Latency   p99.9 Latency       KB/sec


        Returns:
            Dictionary containing parsed metrics, including:
                - threads: Threads used,
                - connections_per_thread: Clients per thread
                - requests_per_client: Requests made per client
                - Set_Ops/sec: The number of SET operations performed per second.
                - Set_Hits/sec: Not usually applicable for writes, but represents successful SET completions in this context.
                - Set_Misses/sec: Failed SET operations per second.
                - Set_Avg._Latency: The average time (usually in milliseconds) taken to complete a SET request.
                - Set_p50_Latency: The median latency; 50% of SET operations were faster than this value.
                - Set_p99_Latency: The tail latency; 99% of SET operations were faster than this value.
                - Set_p99.9_Latency: Extreme tail latency; only 0.1% of SET requests took longer than this.
                - Set_KB/sec: The network throughput for SET operations in kilobytes per second.
                - Get_Ops/sec: The number of GET operations performed per second.
                - Get_Hits/sec: The rate of GET requests where the key was successfully found in the database.
                - Get_Misses/sec: The rate of GET requests where the key did not exist.
                - Get_Avg._Latency: The average time taken to retrieve a value.
                - Get_p50_Latency: Median retrieval time for GET operations.
                - Get_p99_Latency: 99th percentile latency for GET operations.
                - Get_p99.9_Latency: 99.9th percentile latency for GET operations.
                - Get_KB/sec: The network throughput (data egress) for GET operations.
                - Wait_Ops/sec: The rate of WAIT commands issued (used in Redis to ensure synchronous replication).
                - Wait_Hits/sec: WAIT commands that successfully met the required replica acknowledgment count.
                - Wait_Misses/sec: WAIT commands that timed out or failed to meet the replica count.
                - Wait_Avg._Latency: Average time spent waiting for synchronous replication acknowledgment.
                - Wait_p50_Latency: Median duration of the WAIT command.
                - Wait_p99_Latency: 99th percentile duration of the WAIT command.
                - Wait_p99.9_Latency: 99.9th percentile duration of the WAIT command.
                - Wait_KB/sec: Minimal throughput, as WAIT commands carry very small payloads.
                - Total_Ops/sec: The combined throughput of all command types (Set + Get + Wait).
                - Total_Hits/sec: The aggregate rate of successful command completions or key hits across the entire test.
                - Total_Misses/sec: The aggregate rate of failed commands or key misses.
                - Total_Avg._Latency: The mean latency of every single request processed during the benchmark.
                - Total_p50_Latency: The global median latency for the entire workload.
                - Total_p99_Latency: The global 99th percentile latency (crucial for Service Level Objectives).
                - Total_p99.9_Latency: The global 99.9th percentile latency, identifying worst-case performance.
                - Total_KB/sec: The total aggregate network bandwidth consumed (ingress and egress).


        Raises:
            Exception: if the table header or the output format is not
            compatible

        Example output:
            {
                "threads": 4,
                "connections_per_thread": 50,
                "requests_per_client": 10000,
                ...
            }
        """
        output = [
            line for line in ctx.run_result.outputs[-1].stdout.split("\n") if line != ""
        ]
        threads = int(output[0].split()[0])
        connections_per_thread = int(output[1].split()[0])
        requests_per_client = int(output[2].split()[0])
        # TODO: implement parser when the --run-count > 1
        start_stats_idx = next(
            (
                i
                for i, line in enumerate(output)
                if "ALL STATS" in line or "AGGREGATED AVERAGE RESULTS" in line
            ),
            None,
        )

        if start_stats_idx is None:
            raise Exception("Table not found starting at index")
        start_stats_idx += 2  # skip the ---- line
        start_dist_idx = output.index("Request Latency Distribution")

        # Parsing the ALL STATS table

        all_stats_headers = output[start_stats_idx].split()

        def parseFloat(value):
            try:
                return float(value)
            except ValueError:
                return None

        result: RecordResult = {
            "threads": threads,
            "connections_per_thread": connections_per_thread,
            "requests_per_client": requests_per_client,
        }

        for raw_row in output[start_stats_idx + 2 : start_dist_idx]:
            row = raw_row.split()
            row_type = row[0]
            for i, value in enumerate(row[1:], start=1):
                header_name = all_stats_headers[i].replace(" ", "_")
                key = f"{row_type}_{header_name}"
                result[key] = parseFloat(value)
        result["throughput"] = result["Totals_Ops/sec"]
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
