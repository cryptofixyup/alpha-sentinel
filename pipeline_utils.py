"""Small deterministic primitives used by the ML pipeline tests and benchmarks."""
from __future__ import annotations

import torch


def flatten_activations(x: torch.Tensor) -> torch.Tensor:
    """Flatten batch/sequence dimensions while preserving feature width."""
    if x.ndim < 2:
        raise ValueError("activations must have at least 2 dimensions")
    return x.reshape(-1, x.shape[-1])


def sae_loss(
    reconstruction: torch.Tensor,
    target: torch.Tensor,
    encoded: torch.Tensor,
    sparsity_weight: float = 1e-3,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Return total loss, reconstruction MSE, and L1 sparsity penalty."""
    if reconstruction.shape != target.shape:
        raise ValueError("reconstruction and target must have identical shapes")
    if sparsity_weight < 0:
        raise ValueError("sparsity_weight must be non-negative")
    mse = torch.mean((reconstruction - target) ** 2)
    sparsity = torch.mean(torch.abs(encoded))
    total = mse + sparsity_weight * sparsity
    return total, mse, sparsity
