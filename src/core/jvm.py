import shlex


def default_jvm_flags(ram, gc):
    ram = int(ram)
    half = max(1, ram // 2)
    gc = (gc or "G1GC").upper()
    out = [f"-Xmx{ram}G", f"-Xms{half}G", "-XX:+UnlockExperimentalVMOptions"]
    if gc == "ZGC":
        out += ["-XX:+UseZGC"]
    elif gc == "PARALLEL":
        out += ["-XX:+UseParallelGC"]
    elif gc == "SERIAL":
        out += ["-XX:+UseSerialGC"]
    else:
        out += [
            "-XX:+UseG1GC",
            "-XX:G1NewSizePercent=20",
            "-XX:G1ReservePercent=20",
            "-XX:MaxGCPauseMillis=50",
            "-XX:G1HeapRegionSize=32M",
        ]
    out += [
        "-XX:+DisableExplicitGC",
        "-XX:+AlwaysPreTouch",
        "-XX:+ParallelRefProcEnabled",
        "-XX:+PerfDisableSharedMem",
        "-XX:+UseStringDeduplication",
        "-XX:+OptimizeStringConcat",
        "-Dfile.encoding=UTF-8",
        "-Dstdout.encoding=UTF-8",
        "-Dstderr.encoding=UTF-8",
        "-Dminecraft.launcher.brand=xeria",
        "-Dminecraft.launcher.version=1.0",
        "-Dlog4j2.formatMsgNoLookups=true",
        "-Dfml.ignoreInvalidMinecraftCertificates=true",
        "-Dfml.ignorePatchDiscrepancies=true",
    ]
    return out


def default_flags_string(ram="4", gc="G1GC"):
    return " ".join(default_jvm_flags(ram, gc))


def build_jvm_flags(profile, settings, native_dirs, sep):
    ram = int(profile.ram)
    gc = profile.override_gc or settings.get("gc", "G1GC") or "G1GC"

    profile_override = (profile.override_jvm_flags or "").strip()

    user_flags_str = (
        profile_override or (settings.get("default_jvm_flags", "") or "").strip()
    )

    if not user_flags_str:
        user_flags_str = " ".join(default_jvm_flags(ram, gc))

    user_flags = []
    if user_flags_str:
        try:
            user_flags = shlex.split(user_flags_str)
        except Exception:  # noqa: BLE001
            user_flags = user_flags_str.split()

    flags = list(user_flags)
    if native_dirs:
        flags.append(f"-Djava.library.path={sep.join(native_dirs)}")
    return flags
