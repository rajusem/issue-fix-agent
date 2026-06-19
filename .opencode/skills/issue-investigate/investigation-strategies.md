# Investigation Strategies

Targeted investigation approaches based on signal classification.
Read and follow the section matching the detected signal from Phase 1.

## Git History Strategy (signal: regression)

When the issue description indicates something was working before:

1. Check recent commits on the affected branch:
   ```bash
   git log --oneline -20 --since="2 weeks ago"
   ```
2. If a specific timeframe is mentioned ("broke last Tuesday",
   "after PR #123"), narrow the log:
   ```bash
   git log --oneline --after="<date>" --before="<date>"
   ```
3. For each recent commit, check if it touches relevant files:
   ```bash
   git log --oneline --all -- <affected_file_paths>
   ```
4. If a suspect commit is found, analyze its diff:
   ```bash
   git show <commit_sha> -- <affected_files>
   ```
5. Use git blame on the affected lines:
   ```bash
   git blame -L <start>,<end> <file>
   ```
6. If the **Commit** field was provided in the ticket, analyze
   that specific commit as the primary suspect:
   ```bash
   git diff <commit>~1 <commit>
   ```

This strategy finds root causes FAST for regressions because it
looks at what CHANGED, not what EXISTS.

## Dependency Strategy (signal: dependency)

When the issue involves a package/library change:

1. Check for recent changes to dependency files:
   ```bash
   git log --oneline -10 -- go.mod go.sum package.json \
     package-lock.json pnpm-lock.yaml pyproject.toml \
     requirements.txt Pipfile.lock pom.xml build.gradle
   ```
2. Diff the dependency file against the previous version:
   ```bash
   git diff HEAD~5 -- <lockfile>
   ```
3. Identify which dependencies changed and by how much:
   - Major version bump → check for breaking changes
   - Minor/patch → check changelogs for relevant regressions
4. Focus investigation on code that uses the changed dependency:
   ```bash
   grep -rn "import.*<package>" --include="*.{go,py,ts,java}"
   ```

## Concurrency Strategy (signal: concurrency)

When the issue is intermittent or timing-dependent:

1. Search for concurrency primitives in affected code:
   - Go: goroutine, chan, sync.Mutex, sync.WaitGroup, context
   - Python: threading, asyncio, multiprocessing, Lock
   - Java: synchronized, volatile, CompletableFuture, ExecutorService
   - TypeScript: Promise, async/await, setTimeout, setInterval
2. Look for shared mutable state:
   - Global variables accessed by multiple threads/goroutines
   - Caches without synchronization
   - Database connections shared across requests
3. Check for race condition patterns:
   - Read-then-write without locking (check-then-act)
   - Missing context cancellation propagation
   - Unprotected map access in Go
   - Shared slice/array modification
4. Check for timing-dependent code:
   - Hardcoded timeouts or sleeps
   - Retry logic without backoff
   - Order-dependent initialization

## Environment Strategy (signal: environment)

When behavior differs across environments:

1. Compare CI and local configurations:
   ```bash
   find . -name ".github" -o -name ".gitlab-ci.yml" \
     -o -name "Jenkinsfile" -o -name "Dockerfile" | head -10
   ```
2. Check for environment-dependent code:
   ```bash
   grep -rn "os.Getenv\|process.env\|os.environ" \
     --include="*.{go,py,ts,java}" | head -20
   ```
3. Look for file path assumptions:
   - Absolute paths that differ between environments
   - Temp directory differences
4. Check container/OS differences:
   - Dockerfile base image vs local OS
   - Library version differences

## Performance Strategy (signal: performance)

When the issue involves speed degradation or resource exhaustion:

1. Look for N+1 query patterns:
   - ORM queries in loops
   - Missing JOIN/eager loading
2. Check for unbounded operations:
   - Missing pagination on database queries
   - Unbounded in-memory collections
   - Recursive functions without depth limits
3. Look for missing caching:
   - Repeated expensive computations
   - Redundant API calls
4. Check for blocking operations in async paths:
   - Synchronous I/O in async handlers
   - Missing connection pool limits
5. Check recent changes that could affect performance:
   ```bash
   git log --oneline -10 -- <affected_paths>
   ```
