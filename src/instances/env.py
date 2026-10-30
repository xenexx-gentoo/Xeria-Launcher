import os

from core.settings import detect_gpu


def build_launch_env(profile, settings):
    env = os.environ.copy()
    nvidia_fix = getattr(profile, "override_nvidia_fix", False) or settings.get(
        "auto_nvidia_fix", False
    )
    if nvidia_fix and detect_gpu() == "nvidia":
        env["__GL_THREADED_OPTIMIZATIONS"] = "0"
    for src in (settings.get("env_vars", "") or "", profile.override_env_vars or ""):
        for line in src.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env
