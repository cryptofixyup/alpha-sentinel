import asyncio

import pytest
import torch

from auto_labeler import label_text
from pipeline_utils import flatten_activations, sae_loss


def test_tensor_flattening_shapes():
    x = torch.randn(2, 3, 8)
    flattened = flatten_activations(x)
    assert flattened.shape == (6, 8)
    assert torch.equal(flattened[0], x[0, 0])


def test_sae_loss_threshold_and_sparsity():
    target = torch.ones(4, 8)
    reconstruction = target.clone()
    encoded = torch.zeros(4, 16)
    total, mse, sparsity = sae_loss(reconstruction, target, encoded)
    assert mse.item() == pytest.approx(0.0)
    assert sparsity.item() == pytest.approx(0.0)
    assert total.item() == pytest.approx(0.0)


def test_sae_loss_includes_sparsity_penalty():
    target = torch.zeros(2, 2)
    reconstruction = torch.zeros(2, 2)
    encoded = torch.ones(2, 2)
    total, mse, sparsity = sae_loss(reconstruction, target, encoded, sparsity_weight=0.25)
    assert mse.item() == pytest.approx(0.0)
    assert sparsity.item() == pytest.approx(1.0)
    assert total.item() == pytest.approx(0.25)


def test_labeler_rejects_empty_input():
    with pytest.raises(ValueError):
        asyncio.run(label_text("   "))
