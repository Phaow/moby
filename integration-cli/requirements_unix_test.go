//go:build !windows
// +build !windows

package main

import (
	"bytes"
	"os"
	"os/exec"
	"strings"

	"github.com/docker/docker/pkg/sysinfo"
)

var (
	// SysInfo stores information about which features a kernel supports.
	SysInfo *sysinfo.SysInfo
)

func cpuCfsPeriod() bool {
	return testEnv.DaemonInfo.CPUCfsPeriod
}

func cpuCfsQuota() bool {
	return testEnv.DaemonInfo.CPUCfsQuota
}

func cpuShare() bool {
	return testEnv.DaemonInfo.CPUShares
}

func oomControl() bool {
	return testEnv.DaemonInfo.OomKillDisable
}

func pidsLimit() bool {
	return SysInfo.PidsLimit
}

func memoryLimitSupport() bool {
	return testEnv.DaemonInfo.MemoryLimit
}

func memoryReservationSupport() bool {
	return SysInfo.MemoryReservation
}

func swapMemorySupport() bool {
	return testEnv.DaemonInfo.SwapLimit
}

func memorySwappinessSupport() bool {
	return testEnv.IsLocalDaemon() && SysInfo.MemorySwappiness
}

func blkioWeight() bool {
	return testEnv.IsLocalDaemon() && SysInfo.BlkioWeight
}

func cgroupCpuset() bool {
	return testEnv.DaemonInfo.CPUSet
}

// CgroupVersion returns the cgroup version ("1" or "2")
func CgroupVersion() string {
	return testEnv.DaemonInfo.CgroupVersion
}

// IsCgroupV2 returns true if the system uses cgroup v2
func IsCgroupV2() bool {
	return testEnv.DaemonInfo.CgroupVersion == "2"
}

// GetCgroupCPUQuotaFile returns the correct cgroup v1 or v2 cpu quota file path
func GetCgroupCPUQuotaFile() string {
	if IsCgroupV2() {
		return "/sys/fs/cgroup/cpu.max"
	}
	return "/sys/fs/cgroup/cpu/cpu.cfs_quota_us"
}

// GetCgroupCPUPeriodFile returns the correct cgroup v1 or v2 cpu period file path
func GetCgroupCPUPeriodFile() string {
	if IsCgroupV2() {
		return "/sys/fs/cgroup/cpu.max" // cgroup v2 uses cpu.max which contains both quota and period
	}
	return "/sys/fs/cgroup/cpu/cpu.cfs_period_us"
}

// GetCgroupCPUSharesFile returns the correct cgroup v1 or v2 cpu shares file path
func GetCgroupCPUSharesFile() string {
	if IsCgroupV2() {
		return "/sys/fs/cgroup/cpu.weight"
	}
	return "/sys/fs/cgroup/cpu/cpu.shares"
}

// GetCgroupCpusetCpusFile returns the correct cgroup cpuset cpus file path
func GetCgroupCpusetCpusFile() string {
	if IsCgroupV2() {
		return "/sys/fs/cgroup/cpuset.cpus"
	}
	return "/sys/fs/cgroup/cpuset/cpuset.cpus"
}

// GetCgroupCpusetMemsFile returns the correct cgroup cpuset mems file path
func GetCgroupCpusetMemsFile() string {
	if IsCgroupV2() {
		return "/sys/fs/cgroup/cpuset.mems"
	}
	return "/sys/fs/cgroup/cpuset/cpuset.mems"
}

// GetCgroupBlkioWeightFile returns the correct cgroup v1 or v2 blkio weight file path
func GetCgroupBlkioWeightFile() string {
	if IsCgroupV2() {
		return "/sys/fs/cgroup/io.weight"
	}
	return "/sys/fs/cgroup/blkio/blkio.weight"
}

// GetCgroupMemoryLimitFile returns the correct cgroup v1 or v2 memory limit file path
func GetCgroupMemoryLimitFile() string {
	if IsCgroupV2() {
		return "/sys/fs/cgroup/memory.max"
	}
	return "/sys/fs/cgroup/memory/memory.limit_in_bytes"
}

// GetCgroupMemoryReservationFile returns the correct cgroup v1 or v2 memory soft limit file path
func GetCgroupMemoryReservationFile() string {
	if IsCgroupV2() {
		return "/sys/fs/cgroup/memory.soft_limit_in_bytes"
	}
	return "/sys/fs/cgroup/memory/memory.soft_limit_in_bytes"
}

// GetCgroupPidsLimitFile returns the correct cgroup pids limit file path
func GetCgroupPidsLimitFile() string {
	if IsCgroupV2() {
		return "/sys/fs/cgroup/pids.max"
	}
	return "/sys/fs/cgroup/pids/pids.max"
}

// GetCgroupDevicesListFile returns the correct cgroup v1 or v2 devices list file path
func GetCgroupDevicesListFile() string {
	if IsCgroupV2() {
		return "/sys/fs/cgroup/devices.list"
	}
	return "/sys/fs/cgroup/devices/devices.list"
}

// GetCgroupMemorySwappinessFile returns the correct cgroup memory swappiness file path
func GetCgroupMemorySwappinessFile() string {
	if IsCgroupV2() {
		return "/sys/fs/cgroup/memory.swappiness"
	}
	return "/sys/fs/cgroup/memory/memory.swappiness"
}

// GetCgroupSwapLimitFile returns the correct cgroup v1 or v2 swap limit file path
// Note: cgroup v2 uses memory.swap.max instead of memory.memsw.limit_in_bytes
func GetCgroupSwapLimitFile() string {
	if IsCgroupV2() {
		return "/sys/fs/cgroup/memory.swap.max"
	}
	return "/sys/fs/cgroup/memory/memory.memsw.limit_in_bytes"
}

func seccompEnabled() bool {
	return SysInfo.Seccomp
}

func bridgeNfIptables() bool {
	return !SysInfo.BridgeNFCallIPTablesDisabled
}

func unprivilegedUsernsClone() bool {
	content, err := os.ReadFile("/proc/sys/kernel/unprivileged_userns_clone")
	return err != nil || !strings.Contains(string(content), "0")
}

func overlayFSSupported() bool {
	cmd := exec.Command(dockerBinary, "run", "--rm", "busybox", "/bin/sh", "-c", "cat /proc/filesystems")
	out, err := cmd.CombinedOutput()
	if err != nil {
		return false
	}
	return bytes.Contains(out, []byte("overlay\n"))
}

func init() {
	if testEnv.IsLocalDaemon() {
		SysInfo = sysinfo.New()
	}
}
