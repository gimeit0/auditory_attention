"""Tiny CPU test fixture. NOT the production model or a production attestation."""

import torch


def forbidden_backend(graph, example_inputs):
    raise AssertionError("Compiled forward must never run in the eager candidate")


class Features(torch.nn.Module):
    def full_rep(self, signal, background):
        return signal.square(), background


class Network(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.linear = torch.nn.Linear(8, 800)

    def forward(self, cue, scene, mask):
        return self.linear((scene + cue * 0.5).flatten(1))


class BinauralAttentionModule(torch.nn.Module):
    def __init__(self, config):
        super().__init__()
        self.model = Network()
        if config.get("compile_model", False):
            self.model = torch.compile(self.model, backend=forbidden_backend)
        self.coch_gram = Features()
        self.register_buffer("example_buffer", torch.tensor(0.0))
        self.restored = False

    def on_load_checkpoint(self, checkpoint):
        self.restored = True

    def audio_transforms(self, signal, background):
        return signal * 0.75, background

    def forward(self, cue, scene, mask):
        return self.model(cue, scene, mask)
