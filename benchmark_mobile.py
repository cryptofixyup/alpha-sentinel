"""CPU-only benchmark for the deterministic tensor path."""
from __future__ import annotations

import argparse
import time

import torch

from pipeline_utils import flatten_activations


def benchmark(batch: int, sequence: int, features: int, iterations: int) -> float:
    x = torch.randn(batch, sequence, features)
    start = time.perf_counter()
    for _ in range(iterations):
        flatten_activations(x)
    return (time.perf_counter() - start) / iterations


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--sequence", type=int, default=128)
    parser.add_argument("--features", type=int, default=256)
    parser.add_argument("--iterations", type=int, default=100)
    args = parser.parse_args()
    seconds = benchmark(args.batch, args.sequence, args.features, args.iterations)
    print(f"mean_flatten_seconds={seconds:.8f}")


if __name__ == "__main__":
    main()
