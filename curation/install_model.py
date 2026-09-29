"""Download pinned official artifacts locally; never install system packages."""
import hashlib
import argparse
import json
from pathlib import Path
import tarfile
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
MODEL_REPO = "Qwen/Qwen2.5-0.5B-Instruct-GGUF"
MODEL_REVISION = "9217f5db79a29953eb74d5343926648285ec7e67"
MODEL_FILE = "qwen2.5-0.5b-instruct-q4_k_m.gguf"
MODEL_SHA = "74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db"
RUNTIME_TAG = "b11146"
RUNTIME_FILE = "llama-b11146-bin-ubuntu-x64.tar.gz"
RUNTIME_SHA = "c150306eb16b5ab696f76a8bdf810c35fd98a24e82158742e6fa28f420ff8410"


def sha256(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def download(url, path, expected):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and sha256(path) == expected:
        print(f"Verified existing {path.name}", flush=True)
        return
    temporary = path.with_suffix(path.suffix + ".partial")
    print(f"Downloading {path.name}", flush=True)
    with urlopen(url, timeout=60) as response, temporary.open("wb") as f:
        while block := response.read(1024 * 1024):
            f.write(block)
    if sha256(temporary) != expected:
        raise ValueError(f"Checksum mismatch for {path.name}; refusing to use it")
    temporary.replace(path)
    print(f"Verified SHA-256: {path.name}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gpu", action="store_true", help="Install CUDA 13.4 runtime for an NVIDIA GPU")
    args = parser.parse_args()
    model = ROOT / "models" / MODEL_FILE
    archive = ROOT / ".runtime" / RUNTIME_FILE
    download(f"https://huggingface.co/{MODEL_REPO}/resolve/{MODEL_REVISION}/{MODEL_FILE}", model, MODEL_SHA)
    download(f"https://github.com/ggml-org/llama.cpp/releases/download/{RUNTIME_TAG}/{RUNTIME_FILE}", archive, RUNTIME_SHA)
    runtime = ROOT / ".runtime" / RUNTIME_TAG
    runtime.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as tar:
        tar.extractall(runtime, filter="data")
    binary = next(runtime.rglob("llama-server"))
    manifest = {"repository": MODEL_REPO, "revision": MODEL_REVISION, "file": str(model.relative_to(ROOT)),
        "sha256": MODEL_SHA, "runtime_tag": RUNTIME_TAG, "runtime_sha256": RUNTIME_SHA,
        "server": str(binary.relative_to(ROOT)), "quantization": "Q4_K_M", "device": "CPU"}
    if args.gpu:
        gpu_dir = ROOT / ".runtime" / (RUNTIME_TAG + "-cuda")
        gpu_dir.mkdir(parents=True, exist_ok=True)
        artifacts = [
            ("llama-b11146-bin-ubuntu-cuda-13.4-x64.tar.gz", "1603d9c00a4b6eac8298c5c7868cdb080a3ac31948ab1e457441d71ce274dd7e"),
            ("cudart-llama-b11146-bin-ubuntu-cuda-13.4-x64.tar.gz", "7c2af505f8b26ecd3707ab7723fa985fee1df233b7c1d60e5e17724b536d15bb")]
        for name, checksum in artifacts:
            target = ROOT / ".runtime" / name
            download(f"https://github.com/ggml-org/llama.cpp/releases/download/{RUNTIME_TAG}/{name}", target, checksum)
            with tarfile.open(target) as tar:
                tar.extractall(gpu_dir, filter="data")
        gpu_binary = next(gpu_dir.rglob("llama-server"))
        manifest.update(server=str(gpu_binary.relative_to(ROOT)), device="CUDA",
            gpu_artifacts=[{"file": name, "sha256": checksum} for name, checksum in artifacts])
    (ROOT / "models" / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Ready: python -m curation.model_server", flush=True)


if __name__ == "__main__":
    main()
