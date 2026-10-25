"""ALPHA02 CPU numeric jobs: locked ridge/LightGBM training and feature-only prediction.

Needs the `numeric` extra (numpy, LightGBM). The contract package does not import it.
BLAS/OpenMP are pinned to one thread before numpy loads so sums run in a fixed order.
"""
import os

for _name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_name, '1')
