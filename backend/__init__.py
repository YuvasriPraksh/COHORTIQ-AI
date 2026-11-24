"""CohortIQ AI FastAPI backend package.

This file makes ``backend`` a regular package so test modules under
``backend/tests`` are imported as ``backend.tests.*`` with the project root on
``sys.path``. Without it, pytest's default import mode prepends ``backend/`` to
``sys.path`` and ``import app`` resolves to ``backend/app`` instead of the
root-level ``app`` package.
"""
