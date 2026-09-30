"""One fresh-process OpenCV-only run, optionally instrumenting actual cv2 calls."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

FUNCTIONS = ("resize", "cvtColor", "Laplacian", "calcHist", "normalize", "compareHist",
             "goodFeaturesToTrack", "calcOpticalFlowPyrLK", "estimateAffinePartial2D",
             "transform", "imwrite")


def instrumentation(stack: ExitStack, cv2, stats: dict):
    def wrap(name, function):
        def measured(*args, **kwargs):
            started = time.perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                item = stats.setdefault(name, {"calls": 0, "seconds": 0.0})
                item["calls"] += 1
                item["seconds"] += time.perf_counter() - started
        return measured

    class Proxy:
        def __init__(self, target, label):
            self.target, self.label = target, label

        def __getattr__(self, name):
            value = getattr(self.target, name)
            if callable(value) and name in {"read", "get", "set", "release", "isOpened", "detectAndCompute", "knnMatch"}:
                return wrap(f"{self.label}.{name}", value)
            return value

    for name in FUNCTIONS:
        stack.enter_context(patch.object(cv2, name, wrap(name, getattr(cv2, name))))
    for name, label in (("VideoCapture", "VideoCapture"), ("ORB_create", "ORB"), ("BFMatcher", "BFMatcher")):
        original = getattr(cv2, name)

        def factory(*args, _original=original, _label=label, **kwargs):
            return Proxy(_original(*args, **kwargs), _label)

        stack.enter_context(patch.object(cv2, name, factory))


def execute(video: Path, profile: bool, threads: int) -> dict:
    # Runtime accounting is Linux-only; keep importing the CLI/test helpers portable.
    import resource
    import cv2
    import app.vision.video_processor as processor
    from app.runtime_evidence import collect_runtime_evidence
    from scripts.step13_benchmark_worker import _output_signature
    from scripts.step35_pipelines import digest

    cv2.setNumThreads(threads)
    cv2.ocl.setUseOpenCL(False)
    runtime = collect_runtime_evidence(repo_root=Path(__file__).resolve().parents[1],
                                       input_s3_key=None, processing_parameters={"sample_every_seconds": 1.0})
    # The shared collector detects host installation markers. A stock cv2 on
    # the COOL AMI can therefore be labeled COOL; derive backend from actual import.
    runtime["host_cool_installation_version"] = runtime.get("cool_version")
    backend_is_cool = str(Path(cv2.__file__).resolve()).startswith("/opt/cool/")
    runtime["runtime"] = "COOL" if backend_is_cool else "stock"
    if not backend_is_cool:
        runtime["cool_version"] = None
    runtime.update({"opencv_threads": cv2.getNumThreads(), "opencv_optimized": cv2.useOptimized(),
                    "opencv_opencl": cv2.ocl.useOpenCL(), "logical_cpus": os.cpu_count()})
    stats = {}
    with tempfile.TemporaryDirectory(prefix="rentready-step35-cool-") as directory:
        with ExitStack() as stack:
            stack.enter_context(patch.object(processor, "collect_runtime_evidence", lambda **_: runtime))
            if profile:
                instrumentation(stack, cv2, stats)
            before = resource.getrusage(resource.RUSAGE_SELF)
            started = time.perf_counter()
            manifest = processor.process_video(video, Path(directory), sample_every_seconds=1.0)
            elapsed = time.perf_counter() - started
            after = resource.getrusage(resource.RUSAGE_SELF)
        # Hashes and output verification are excluded from headline timings.
        hashes = []
        for frame in manifest["keyframes"]:
            image = cv2.imread(frame["local_path"])
            if image is None:
                raise ValueError("Missing output image")
            hashes.append({"frame_number": frame["frame_number"], "shape": list(image.shape),
                           "decoded_pixels_sha256": hashlib.sha256(image.tobytes()).hexdigest()})
        signature = _output_signature(manifest)
    cpu = after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime
    return {"input_sha256": digest(video), "profiled": profile, "runtime": runtime,
            "wall_seconds": elapsed, "cpu_seconds": cpu,
            "cpu_utilization_percent_instance": cpu / elapsed / max(1, os.cpu_count()) * 100,
            "peak_memory_mib": after.ru_maxrss / 1024,
            "sampled_frames": manifest["processing"]["sampled_frames"],
            "sampled_frames_per_second": manifest["processing"]["sampled_frames"] / elapsed,
            "signature": signature, "decoded_image_hashes": hashes, "functions": stats}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("video", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--profile", action="store_true")
    p.add_argument("--threads", type=int, default=16)
    args = p.parse_args()
    if args.threads < 1:
        p.error("threads must be positive")
    result = execute(args.video.resolve(), args.profile, args.threads)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
