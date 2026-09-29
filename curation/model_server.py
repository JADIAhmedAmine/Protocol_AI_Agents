import argparse
import json
import os
from pathlib import Path
from .install_model import ROOT


def main():
    parser = argparse.ArgumentParser(description="Serve the installed Qwen model locally.")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--cpu", action="store_true", help="Disable GPU offload")
    parser.add_argument("--verbose", action="store_true", help="Log device placement and layer offload")
    args = parser.parse_args()
    manifest = ROOT / "models" / "manifest.json"
    if not manifest.exists():
        parser.exit(1, "Run python -m curation.install_model first.\n")
    config = json.loads(manifest.read_text())
    binary = str(ROOT / config["server"])
    local_libs = ROOT / ".runtime" / "system-libs" / "usr" / "lib" / "x86_64-linux-gnu"
    libraries = [str(local_libs), str(Path(binary).parent), "/usr/lib/wsl/lib"]
    gpu_dir = ROOT / ".runtime" / (config["runtime_tag"] + "-cuda")
    if gpu_dir.exists():
        libraries.extend(str(p.parent) for p in gpu_dir.rglob("libcudart.so*"))
    os.environ["LD_LIBRARY_PATH"] = ":".join(libraries) + ":" + os.environ.get("LD_LIBRARY_PATH", "")
    os.execv(binary, [binary, "-m", str(ROOT / config["file"]), "--host", "127.0.0.1",
        "--port", str(args.port), "--threads", str(args.threads), "--ctx-size", "4096",
        "--parallel", "1", "--n-gpu-layers", "0" if args.cpu or config["device"] == "CPU" else "99",
        "--alias", "local-qwen", "--no-webui", *(["--verbose"] if args.verbose else [])])


if __name__ == "__main__":
    main()
