#!/bin/bash
#
# Moby Integration-CLI Test Runner
# Features: GOPATH setup, cache pruning, dependency installation, structured reporting, skip known failures
#

set -e

# ========== Configuration ==========
GOPATH_DIR="${GOPATH_DIR:-/tmp/gopath}"
export GOPATH="$GOPATH_DIR"
export DOCKER_HOST="${DOCKER_HOST:-unix:///var/run/docker.sock}"
export DOCKER_BUILDKIT=0
export GO111MODULE="${GO111MODULE:-off}"
REPORT_DIR="${REPORT_DIR:-$(pwd)/report-$(date +%Y%m%d_%H%M%S)}"

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

DRY_RUN=${DRY_RUN:-false}

# Log with timestamp + level + message (English)
log_with_timestamp() {
    local level="$1"
    local color="$2"
    shift 2
    echo -e "${color}[$(date '+%Y-%m-%d %H:%M:%S')] [${level}]${NC} $*"
}

log_info() {
    log_with_timestamp "INFO" "$GREEN" "$@"
}

log_step() {
    log_with_timestamp "STEP" "$BLUE" "$@"
}

log_warn() {
    log_with_timestamp "WARN" "$YELLOW" "$@"
}

log_error() {
    log_with_timestamp "ERROR" "$RED" "$@" >&2
}

# Aliases for backwards compatibility
echo_step() { log_step "$@"; }
echo_warn() { log_warn "$@"; }
echo_error() { log_error "$@"; }

SUDO=${SUDO:-sudo}

# Default tests to skip (known incompatibilities)
# NOTE: Add patterns here as tests are discovered to be incompatible.
# Usage: SKIP_TESTS="Pattern1|Pattern2" runtests.sh
SKIP_TESTS="${SKIP_TESTS:-}"

# Core CLI API compatibility suites (focus mode)
# -run accepts a regex: suite|suite|... to run only matching TestSuite names
# Use -skip to exclude individual tests within those suites
FOCUS_SUITES="${FOCUS_SUITES:-TestDockerAPISuite|TestDockerCLIRunSuite|TestDockerCLICreateSuite|TestDockerCLIStartSuite|TestDockerCLIInspectSuite|TestDockerCLIPsSuite|TestDockerCLILogsSuite|TestDockerCLIExecSuite|TestDockerCLIAttachSuite|TestDockerCLIImagesSuite|TestDockerCLINetworkSuite|TestDockerCLIVolumeSuite|TestDockerCLICpSuite|TestDockerCLIRestartSuite|TestDockerCLIRmiSuite}"

# Dry run mode - show what would be executed (must be before any setup)
if [ "$DRY_RUN" = "true" ]; then
    log_step "DRY RUN - Listing tests that would be executed"
    echo ""
    echo "FOCUS_SUITES: $FOCUS_SUITES"
    echo "SKIP_TESTS: $SKIP_TESTS"
    echo ""
    log_warn "This was a dry run. No tests were executed."
    exit 0
fi

# ========== 1. Setup GOPATH Structure ==========
echo_step "Setting up GOPATH structure..."

DOCKER_LINK_DIR="$GOPATH_DIR/src/github.com/docker"
DOCKER_LINK="$DOCKER_LINK_DIR/docker"
CURRENT_DIR="$(pwd)"

# Create directory if not exists
mkdir -p "$DOCKER_LINK_DIR"

# Create symlink if not exists or points to wrong location
if [ -L "$DOCKER_LINK" ]; then
    TARGET=$(readlink "$DOCKER_LINK" 2>/dev/null) || true
    # Check if symlink is broken (循环链接 or target doesn't exist)
    if [ -z "$TARGET" ] || [ ! -e "$DOCKER_LINK" ]; then
        log_warn "Broken symlink detected, recreating..."
        rm -f "$DOCKER_LINK"
        ln -s "$CURRENT_DIR" "$DOCKER_LINK"
    elif [ "$TARGET" != "$CURRENT_DIR" ]; then
        log_warn "Symlink points to wrong location, recreating..."
        rm -f "$DOCKER_LINK"
        ln -s "$CURRENT_DIR" "$DOCKER_LINK"
    else
        log_info "Symlink already exists and correct: $DOCKER_LINK -> $CURRENT_DIR"
    fi
elif [ -e "$DOCKER_LINK" ]; then
    log_warn "$DOCKER_LINK exists but is not a symlink, skipping"
else
    ln -s "$CURRENT_DIR" "$DOCKER_LINK"
    log_info "Created symlink: $DOCKER_LINK -> $CURRENT_DIR"
fi

# Change to GOPATH directory
log_step "Changing to GOPATH directory..."
cd "$DOCKER_LINK"

# ========== 2. Install Dependencies ==========
log_step "Checking and installing dependencies..."

if ! command -v git &> /dev/null; then
    log_warn "git not found, installing..."
    $SUDO dnf install -y git
fi

if ! command -v pkg-config &> /dev/null || ! pkg-config --exists devmapper 2>/dev/null; then
    log_warn "device-mapper-devel not found, installing..."
    $SUDO dnf install -y device-mapper-devel
fi

# Check and install gotestsum
if ! command -v gotestsum &> /dev/null; then
    log_warn "gotestsum not found, installing..."
    go install gotest.tools/gotestsum@latest
    export PATH="$PATH:$(go env GOPATH)/bin"
fi

# ========== 3. Clear BuildKit Cache ==========
log_step "Clearing BuildKit cache..."
docker builder prune -a -f

# ========== 4. Run Tests ==========
log_step "Running tests..."

# Report files
JSON_REPORT="${REPORT_DIR}/test-report.json"
XML_REPORT="${REPORT_DIR}/test-report.xml"

# Create report directory
mkdir -p "$REPORT_DIR"

# Default timeout
TIMEOUT="${TIMEOUT:-6h}"

# Record start time for elapsed calculation
TEST_START=$(date +%s)

# Build skip arg only if SKIP_TESTS is non-empty
SKIP_ARGS=()
if [ -n "$SKIP_TESTS" ]; then
    SKIP_ARGS=("-test.skip" "$SKIP_TESTS")
fi

# Run tests with gotestsum for structured reporting
gotestsum --format=standard-verbose \
    --jsonfile="${JSON_REPORT}" \
    --junitfile="${XML_REPORT}" \
    -- \
    -timeout "$TIMEOUT" ./integration-cli/... \
    -run "$FOCUS_SUITES" \
    "${SKIP_ARGS[@]}" \
    -count=1 \
    "$@" || true
TEST_END=$(date +%s)
TEST_ELAPSED=$((TEST_END - TEST_START))

# Format elapsed time
format_elapsed() {
    local s=$1
    local h=$((s / 3600))
    local m=$(((s % 3600) / 60))
    local sec=$((s % 60))
    if [ $h -gt 0 ]; then
        printf "%dh %dm %ds" $h $m $sec
    elif [ $m -gt 0 ]; then
        printf "%dm %ds" $m $sec
    else
        printf "%ds" $sec
    fi
}

TEST_ELAPSED_FMT=$(format_elapsed $TEST_ELAPSED)

log_step "Tests completed!"
log_info "Total elapsed time: ${TEST_ELAPSED_FMT} (${TEST_ELAPSED}s)"
log_info "Report directory: ${REPORT_DIR}"
log_info "  - JSON: ${JSON_REPORT}"
log_info "  - XML:  ${XML_REPORT}"
