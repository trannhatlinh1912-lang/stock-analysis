"""One-command daily pipeline orchestrator.

Runs all framework v3.0 steps in correct order with:
  - Skip-on-fresh-cache (avoid redundant API calls)
  - Per-step timing log
  - Rate-limit aware (retry once after sleep)
  - Aggregate exit code (0 if all critical steps OK)
  - Per-step error capture without failing entire pipeline

Step groups:
  GROUP A — fundamentals/liquidity (quarterly cadence, skip if fresh ≤90d)
  GROUP B — daily market data (VN-Index, VN30 liquidity, foreign snapshot)
  GROUP C — sector cycle proxies (quarterly cadence, skip if fresh ≤14d)
  GROUP D — daily layer computation (L1 quality → L6 technical → L7 lai)
  GROUP E — orchestrator (screen → sizing → entry/exit plan)

Critical steps (failure breaks pipeline):
  market_regime, sector_regime, quality_gate, screen_watchlist
Non-critical (failure logged but pipeline continues):
  foreign/insider snapshots, sector cycle proxies, sizing/entry_exit (depend on PASS)

Usage:
  python3 scripts/run_daily.py            # full daily run
  python3 scripts/run_daily.py --quick    # skip fetch_fundamentals + technical_runner full fetch
  python3 scripts/run_daily.py --resume   # skip steps with fresh outputs (default)
  python3 scripts/run_daily.py --force    # ignore cache, redo all
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DATA = ROOT / "data"


def _is_fresh(path: Path, max_age_days: int) -> bool:
    if not path.exists():
        return False
    age_days = (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).days
    return age_days <= max_age_days


def _step(name: str, cmd: list[str], critical: bool, timeout: int = 600) -> dict:
    start = time.time()
    print(f"\n[{name}] running: {' '.join(cmd[2:])}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        dt = time.time() - start
        if r.returncode == 0:
            print(f"[{name}] OK in {dt:.1f}s")
            return {"name": name, "rc": 0, "dt": dt, "critical": critical}
        # On rate-limit, retry once after sleep
        stderr_tail = (r.stderr or "")[-400:]
        if "rate limit" in stderr_tail.lower() or "Process terminated" in stderr_tail:
            print(f"[{name}] rate-limited, sleeping 60s then retry...")
            time.sleep(60)
            start2 = time.time()
            r2 = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            dt2 = time.time() - start2
            if r2.returncode == 0:
                print(f"[{name}] OK on retry in {dt2:.1f}s")
                return {"name": name, "rc": 0, "dt": dt + dt2, "retried": True, "critical": critical}
            stderr_tail = (r2.stderr or "")[-400:]
        print(f"[{name}] FAIL rc={r.returncode} {'(critical)' if critical else '(non-critical)'}")
        if stderr_tail:
            print(f"  stderr tail: {stderr_tail}")
        return {"name": name, "rc": r.returncode, "dt": dt, "critical": critical,
                "stderr_tail": stderr_tail}
    except subprocess.TimeoutExpired:
        print(f"[{name}] TIMEOUT after {timeout}s")
        return {"name": name, "rc": 124, "dt": timeout, "critical": critical,
                "stderr_tail": "timeout"}
    except Exception as e:
        print(f"[{name}] EXCEPTION {e}")
        return {"name": name, "rc": 99, "dt": time.time() - start, "critical": critical,
                "stderr_tail": str(e)[:200]}


def build_plan(quick: bool, force: bool) -> list[dict]:
    today = date.today().isoformat()
    end = today
    start_3y = (date.today() - timedelta(days=365 * 3)).isoformat()
    start_2y = (date.today() - timedelta(days=365 * 2)).isoformat()
    py = sys.executable

    # Each step: (name, cmd, critical, skip_cache_path, skip_cache_age_days)
    steps: list[dict] = []

    # GROUP A — fundamentals/liquidity (quarterly, skip if fresh ≤90d)
    if not quick:
        steps.append({
            "name": "fetch_fundamentals",
            "cmd": [py, str(SCRIPTS / "fetch_fundamentals.py")],
            "critical": False,
            "skip_if_fresh": (DATA / "fundamentals" / "VCB.json", 90),
            "timeout": 1800,
        })
        steps.append({
            "name": "fetch_liquidity",
            "cmd": [py, str(SCRIPTS / "fetch_liquidity.py")],
            "critical": False,
            "skip_if_fresh": (DATA / "liquidity" / "VCB.json", 1),
            "timeout": 900,
        })

    # GROUP B — daily market data
    steps.append({
        "name": "market_context",
        "cmd": [py, str(SCRIPTS / "market_context.py"), "--start", start_2y, "--end", end],
        "critical": True,
        "skip_if_fresh": (DATA / f"market_context_{today}.json", 1),
        "timeout": 120,
    })
    steps.append({
        "name": "vn30_liquidity_daily",
        "cmd": [py, str(SCRIPTS / "vn30_liquidity_daily.py")],
        "critical": False,
        "skip_if_fresh": (DATA / f"vn30_liquidity_{today}.json", 1),
        "timeout": 600,
    })
    steps.append({
        "name": "foreign_snapshot_daily",
        "cmd": [py, str(SCRIPTS / "foreign_snapshot_daily.py")],
        "critical": False,
        "skip_if_fresh": (DATA / f"foreign_snapshot_run_{today}.json", 1),
        "timeout": 600,
    })

    # GROUP C — sector cycle proxies (quarterly, skip if fresh ≤14d)
    for sector_script, sector_name in [
        ("banking_nim_proxy.py", "banking"),
        ("re_ocf_trend.py", "real_estate"),
        ("steel_inv_turnover.py", "steel"),
        ("consumer_sssg_proxy.py", "consumer"),
    ]:
        steps.append({
            "name": f"cycle_{sector_name}",
            "cmd": [py, str(SCRIPTS / "sector_cycle" / sector_script)],
            "critical": False,
            "skip_if_fresh": (DATA / "sector_cycle" / f"{sector_name}_{today}.json", 14),
            "timeout": 600,
        })
    # Tech sector also uses revenue YoY proxy via consumer_sssg
    steps.append({
        "name": "cycle_tech",
        "cmd": [py, str(SCRIPTS / "sector_cycle" / "consumer_sssg_proxy.py"), "--sector", "tech"],
        "critical": False,
        "skip_if_fresh": (DATA / "sector_cycle" / f"tech_{today}.json", 14),
        "timeout": 600,
    })

    # Insider snapshot — non-critical, slow, optional
    steps.append({
        "name": "insider_snapshot_daily",
        "cmd": [py, str(SCRIPTS / "insider_snapshot_daily.py")],
        "critical": False,
        "skip_if_fresh": None,
        "timeout": 1200,
    })

    # GROUP D — daily layer computation
    steps.append({
        "name": "market_regime",
        "cmd": [py, str(SCRIPTS / "market_regime.py"), "--no-breadth"],
        "critical": True,
        "skip_if_fresh": (DATA / f"market_regime_{today}.json", 1) if not force else None,
        "timeout": 120,
    })
    steps.append({
        "name": "sector_regime",
        "cmd": [py, str(SCRIPTS / "sector_regime.py")],
        "critical": True,
        "skip_if_fresh": (DATA / f"sector_regime_{today}.json", 1) if not force else None,
        "timeout": 600,
    })
    steps.append({
        "name": "quality_gate",
        "cmd": [py, str(SCRIPTS / "quality_gate.py")],
        "critical": True,
        "skip_if_fresh": None,  # cheap, always run
        "timeout": 60,
    })

    tech_cmd = [py, str(SCRIPTS / "technical_runner.py")]
    if quick:
        tech_cmd.append("--skip-fetch")
    steps.append({
        "name": "technical_runner",
        "cmd": tech_cmd,
        "critical": True,
        "skip_if_fresh": None,
        "timeout": 1800,
    })

    steps.append({
        "name": "trading_mode",
        "cmd": [py, str(SCRIPTS / "trading_mode.py")],
        "critical": True,
        "skip_if_fresh": None,
        "timeout": 60,
    })
    steps.append({
        "name": "catalyst_detector",
        "cmd": [py, str(SCRIPTS / "catalyst_detector.py")],
        "critical": True,
        "skip_if_fresh": None,
        "timeout": 60,
    })
    steps.append({
        "name": "valuation_compute",
        "cmd": [py, str(SCRIPTS / "valuation_compute.py")],
        "critical": True,
        "skip_if_fresh": None,
        "timeout": 60,
    })
    steps.append({
        "name": "lai_detector",
        "cmd": [py, str(SCRIPTS / "lai_detector.py"), "--skip-news"],
        "critical": True,
        "skip_if_fresh": None,
        "timeout": 300,
    })

    # GROUP E — orchestrator
    steps.append({
        "name": "screen_watchlist",
        "cmd": [py, str(SCRIPTS / "screen_watchlist.py")],
        "critical": True,
        "skip_if_fresh": None,
        "timeout": 60,
    })
    steps.append({
        "name": "sizing_calculator",
        "cmd": [py, str(SCRIPTS / "sizing_calculator.py")],
        "critical": False,
        "skip_if_fresh": None,
        "timeout": 60,
    })
    steps.append({
        "name": "entry_exit_plan",
        "cmd": [py, str(SCRIPTS / "entry_exit_plan.py")],
        "critical": False,
        "skip_if_fresh": None,
        "timeout": 60,
    })

    return steps


def main() -> int:
    ap = argparse.ArgumentParser(description="Daily framework v3.0 pipeline orchestrator.")
    ap.add_argument("--quick", action="store_true",
                    help="Skip slow steps: fetch_fundamentals/liquidity, technical fetch.")
    ap.add_argument("--force", action="store_true", help="Ignore cache, redo all steps.")
    args = ap.parse_args()

    plan = build_plan(args.quick, args.force)
    today = date.today().isoformat()
    overall_start = time.time()

    print(f"=== run_daily {today} ({len(plan)} steps, quick={args.quick}, force={args.force}) ===")

    results = []
    for step in plan:
        skip_check = step.get("skip_if_fresh")
        if not args.force and skip_check is not None:
            path, max_age = skip_check
            if _is_fresh(path, max_age):
                print(f"\n[{step['name']}] SKIP (fresh: {path.name})")
                results.append({"name": step["name"], "rc": 0, "dt": 0, "skipped": True,
                                "critical": step["critical"]})
                continue
        r = _step(step["name"], step["cmd"], step["critical"], timeout=step.get("timeout", 600))
        results.append(r)

    total_dt = time.time() - overall_start

    # Summary
    print(f"\n=== summary {today} (total {total_dt:.1f}s) ===")
    n_ok = sum(1 for r in results if r["rc"] == 0)
    n_fail_critical = sum(1 for r in results if r["rc"] != 0 and r.get("critical"))
    n_fail_non_critical = sum(1 for r in results if r["rc"] != 0 and not r.get("critical"))
    n_skipped = sum(1 for r in results if r.get("skipped"))
    print(f"  OK={n_ok}  SKIP={n_skipped}  FAIL_critical={n_fail_critical}  FAIL_non_critical={n_fail_non_critical}")
    print()
    for r in results:
        status = "SKIP" if r.get("skipped") else ("OK" if r["rc"] == 0 else f"FAIL_rc={r['rc']}")
        crit_tag = "C" if r["critical"] else " "
        print(f"  [{crit_tag}] {r['name']:30s} {status:14s} ({r['dt']:6.1f}s)")

    # Save full log
    log_path = DATA / f"run_daily_log_{today}.json"
    log_path.write_text(json.dumps({
        "as_of": today,
        "total_dt_seconds": round(total_dt, 1),
        "n_steps": len(results),
        "n_ok": n_ok, "n_skipped": n_skipped,
        "n_fail_critical": n_fail_critical,
        "n_fail_non_critical": n_fail_non_critical,
        "results": results,
    }, ensure_ascii=False, indent=2))
    print(f"\nlog → {log_path}")

    # Print today's screen report path
    screen_md = ROOT / "reports" / f"screen_{today}.md"
    if screen_md.exists():
        print(f"\nreport → {screen_md}")

    return 1 if n_fail_critical > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
