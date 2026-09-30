"""Predeclared G2 matrix. No scheduler, freeze, or production execution entry."""
from dataclasses import dataclass

PROTOCOL = 'formal40_numeric_profiles_20260916_v1'
TRIALS = (9000, 0, 1, 158, 317, 476, 634, 793, 952, 1111, 1269, 1428,
          1587, 1745, 1904, 2063, 2222, 2380, 2539, 2698, 2856, 3015,
          3174, 3333, 3491, 3650, 3809, 3967, 4126, 4285, 4444, 4602)
ORDER = ('R', 'C', 'D', 'E')
PREFERENCE = ('E', 'C', 'D', 'R')
ATOL = 1e-6


@dataclass(frozen=True)
class Profile:
    name: str
    tf32: bool
    compiled: bool

    def runtime(self):
        return dict(deterministic_algorithms=True, cudnn_deterministic=True, cudnn_benchmark=False,
                    float32_matmul_precision='high' if self.tf32 else 'highest',
                    cuda_matmul_allow_tf32=self.tf32, cudnn_allow_tf32=self.tf32)

    def document(self):
        return dict(profile=self.name, protocol=PROTOCOL + '_' + self.name, tf32=self.tf32,
                    compiled=self.compiled, autocast=False, runtime=self.runtime(),
                    pass_batch_sizes=[16, 1], trial_ids=list(TRIALS), forward_calls=34,
                    official_atol=ATOL, production_ready=False)


def profile(name):
    if type(name) is not str or name not in ORDER:
        raise ValueError('exact predeclared profile required')
    return Profile(name, name in ('R', 'D'), name in ('R', 'C'))
